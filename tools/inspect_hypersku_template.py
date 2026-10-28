"""Read-only, header-only check of the documented HyperSKU order template.

Never uploads, imports, authors or recalculates a workbook. Only the documented
16-column customer-order template is the default; inbound-stock explicitly
selects the distinct 2-column stock template. No contract is guessed from data.
Only a single blank sheet is accepted. Sheet names, comments, paths and arbitrary
source text never enter the output. This structure check
is NOT an import test, an API connection or proof of provider authorization.
"""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
EXPECTED_HEADERS = (
    'SKU Code', 'Store ID', 'Order Number', 'Hypersku Quantity', 'First Name',
    'Last Name', 'Address1', 'Address2', 'City', 'Province', 'Country', 'Zip',
    'Phone Number', 'Email', 'POD Text', 'POD Image',
)
INBOUND_STOCK_HEADERS = ('SKU Code', 'Hypersku Quantity')
_CONTRACTS = {'customer-order': EXPECTED_HEADERS, 'inbound-stock': INBOUND_STOCK_HEADERS}
_MAX_FILE = 1024 * 1024
_MAX_EXPANDED = 10 * 1024 * 1024
_MAX_MEMBERS = 256
_MAX_XML_NODES = 100_000
_MAX_ROWS = 10_000
_MAX_CELLS = 100_000
_FORMULA_TAGS = frozenset({
    'f', 'formula', 'formula1', 'formula2', 'calculatedColumnFormula',
    'totalsRowFormula', 'definedName',
})


class TemplateInspectionError(ValueError):
    """Fixed safe diagnostic code, without any untrusted workbook content."""


def _refuse(code):
    raise TemplateInspectionError(code) from None


def _xml(raw):
    # Reject DTD/entities also in UTF-16/32; do not expand untrusted XML.
    normalized = raw.replace(b'\0', b'').upper()
    if b'<!DOCTYPE' in normalized or b'<!ENTITY' in normalized:
        _refuse('template_xml_declaration_not_allowed')
    return ET.fromstring(raw)


def _cell_text(cell, shared):
    if (cell.text and cell.text.strip() or any(child.tag not in
            ('{' + NS['s'] + '}v', '{' + NS['s'] + '}is') for child in cell)
            or any(child.tail and child.tail.strip() for child in cell)):
        _refuse('template_invalid_cell')
    values, inline = cell.findall('s:v', NS), cell.findall('s:is', NS)
    if len(values) > 1 or len(inline) > 1 or (values and inline):
        _refuse('template_invalid_cell')
    if cell.attrib.get('t') == 's' and values:
        index = values[0].text
        if not isinstance(index, str) or re.fullmatch(r'[0-9]{1,8}', index) is None or int(index) >= len(shared):
            _refuse('template_invalid_shared_string')
        return shared[int(index)]
    if inline:
        return ''.join(t.text or '' for t in inline[0].findall('.//s:t', NS))
    return values[0].text if values else None


def _contract(kind):
    if not isinstance(kind, str) or kind not in _CONTRACTS:
        _refuse('template_unknown_kind')
    return _CONTRACTS[kind]


def _inspect_bytes(data, kind):
    expected_headers = _contract(kind)
    expected_columns = ''.join(chr(65 + i) for i in range(len(expected_headers)))
    with ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        expanded = sum(info.file_size for info in infos)
        if len(infos) > _MAX_MEMBERS or len(set(names)) != len(names):
            _refuse('template_invalid_zip_members')
        if expanded > _MAX_EXPANDED:
            _refuse('template_expanded_size_limit')
        if any(info.flag_bits & 1 for info in infos):
            _refuse('template_encrypted_member_not_allowed')
        roots, node_count = {}, 0
        for name in names:
            if name.lower().endswith(('.xml', '.rels')):
                root = _xml(archive.read(name))
                node_count += sum(1 for _ in root.iter())
                if node_count > _MAX_XML_NODES:
                    _refuse('template_xml_node_limit')
                # Formulas are not confined to worksheet cells: conditional
                # formatting, validation, tables, charts and names carry them
                # in separate XML parts. Reject even empty/cached definitions.
                if any(element.tag.rsplit('}', 1)[-1] in _FORMULA_TAGS for element in root.iter()):
                    _refuse('template_formula_not_allowed')
                roots[name] = root
                if name.lower().endswith('.rels'):
                    for relationship in root:
                        target = relationship.attrib.get('Target', '')
                        if (relationship.attrib.get('TargetMode') not in (None, 'Internal')
                                or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target)
                                or target.startswith('//') or '\\' in target):
                            _refuse('template_external_relationship_not_allowed')
        workbook = roots['xl/workbook.xml']
        sheets = workbook.find('s:sheets', NS)
        if sheets is None or len(sheets) != 1 or sheets[0].tag != '{' + NS['s'] + '}sheet':
            _refuse('template_single_sheet_required')
        sheet = sheets[0]
        if sheet.attrib.get('state', 'visible') != 'visible':
            _refuse('template_visible_sheet_required')
        targets = {}
        for relationship in roots['xl/_rels/workbook.xml.rels']:
            identity = relationship.attrib.get('Id')
            if not identity or identity in targets:
                _refuse('template_ambiguous_relationship')
            targets[identity] = relationship.attrib['Target']
        target = targets[sheet.attrib[REL]]
        member = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
        if not member.startswith('xl/worksheets/') or not member.endswith('.xml'):
            _refuse('template_invalid_sheet_target')
        worksheet_members = {name for name, root in roots.items()
                             if root.tag == '{' + NS['s'] + '}worksheet'
                             or name.lower().startswith('xl/worksheets/') and name.lower().endswith('.xml')}
        if worksheet_members != {member}:
            _refuse('template_extra_worksheet_not_allowed')
        worksheet = roots[member]
        if worksheet.tag != '{' + NS['s'] + '}worksheet':
            _refuse('template_invalid_worksheet')
        shared_root = roots.get('xl/sharedStrings.xml')
        shared = ([] if shared_root is None else
                  [''.join(t.text or '' for t in si.findall('.//s:t', NS)) for si in shared_root])
        # Deleted rows can leave private unused shared strings. Do not accept
        # them as a blank template or echo their values in diagnostics.
        if any(text not in expected_headers and text != '' for text in shared):
            _refuse('template_non_header_shared_string')
        containers = worksheet.findall('s:sheetData', NS)
        if len(containers) != 1:
            _refuse('template_invalid_sheet_data')
        if containers[0].text and containers[0].text.strip():
            _refuse('template_invalid_sheet_data')
        rows, seen_rows, seen_cells, headers = list(containers[0]), set(), set(), {}
        if len(rows) > _MAX_ROWS:
            _refuse('template_row_limit')
        for row in rows:
            number = row.attrib.get('r', '')
            if (row.tag != '{' + NS['s'] + '}row' or re.fullmatch(r'[1-9][0-9]{0,6}', number) is None
                    or int(number) > 1_048_576 or number in seen_rows
                    or row.text and row.text.strip() or row.tail and row.tail.strip()):
                _refuse('template_invalid_row')
            seen_rows.add(number)
            for cell in row:
                reference = cell.attrib.get('r', '')
                match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', reference)
                if (cell.tag != '{' + NS['s'] + '}c' or match is None
                        or match[2] != number or reference in seen_cells):
                    _refuse('template_invalid_cell')
                seen_cells.add(reference)
                if len(seen_cells) > _MAX_CELLS:
                    _refuse('template_cell_limit')
                text = _cell_text(cell, shared)
                if number == '1':
                    if text is not None and cell.attrib.get('t') not in ('s', 'inlineStr', 'str'):
                        _refuse('template_invalid_header_cell_type')
                    if len(match[1]) != 1 or match[1] not in expected_columns:
                        if text is not None and text != '':
                            _refuse('template_header_mismatch')
                    else:
                        headers[match[1]] = text
                elif text is not None and text != '':
                    _refuse('template_customer_data_not_allowed')
        if len(worksheet.findall('.//s:c', NS)) != len(seen_cells):
            _refuse('template_invalid_cell_location')
        if tuple(headers.get(column) for column in expected_columns) != expected_headers:
            _refuse('template_header_mismatch')
        comment_count = sum(1 for root in roots.values() for element in root.iter()
                            if element.tag.rsplit('}', 1)[-1] in ('comment', 'threadedComment'))
        return {
            'sha256': sha256(data).hexdigest(), 'kind': kind, 'headers': list(expected_headers),
            'sheet_count': 1, 'rows_scanned': len(rows), 'cells_scanned': len(seen_cells),
            'comment_count': comment_count, 'zip_member_count': len(infos),
            'expanded_bytes': expanded, 'scope': 'read_only_header_only_not_an_import_test',
        }


def inspect_template(path, *, kind='customer-order'):
    """Read once with a hard bound; hash precisely the inspected bytes."""
    try:
        _contract(kind)
        with Path(path).open('rb') as source:
            data = source.read(_MAX_FILE + 1)
        if len(data) > _MAX_FILE:
            _refuse('template_file_size_limit')
        return _inspect_bytes(data, kind)
    except TemplateInspectionError:
        raise
    except (OSError, BadZipFile, ET.ParseError, KeyError, IndexError, ValueError,
            TypeError, RuntimeError, NotImplementedError):
        _refuse('template_invalid_package')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--kind', choices=tuple(_CONTRACTS), default='customer-order',
                        help='Explicit contract: customer order (16 columns) or inbound stock (2)')
    args = parser.parse_args(argv)
    try:
        result = inspect_template(args.path, kind=args.kind)
    except TemplateInspectionError as error:
        parser.exit(2, 'Inspection refused: ' + str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
