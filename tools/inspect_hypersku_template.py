"""Read-only inspection of an official, manually downloaded XLSX template.

Never uploads, imports or authors a workbook. Does not execute Excel formulas.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def inspect_template(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Expected a small provider template, not a customer export')
    sheets = []
    with ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 10 * 1024 * 1024:
            raise ValueError('Unexpected expanded template size')
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(t.text or '' for t in si.findall('.//s:t', NS))
                      for si in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {r.attrib['Id']: r.attrib for r in relationships}
        for sheet in workbook.find('s:sheets', NS):
            name = sheet.attrib['name']
            relationship = targets[sheet.attrib[REL]]
            if relationship.get('TargetMode') == 'External':
                raise ValueError('External workbook target is not a local template sheet')
            target = relationship['Target']
            member = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not member.startswith('xl/worksheets/') or not member.endswith('.xml'):
                raise ValueError('Unexpected workbook sheet target')
            root = ET.fromstring(archive.read(member))
            rows = []
            for row in root.findall('s:sheetData/s:row', NS)[:8]:
                cells = {}
                for cell in row.findall('s:c', NS):
                    value = cell.find('s:v', NS)
                    if value is not None:
                        text = value.text
                        if cell.attrib.get('t') == 's':
                            text = shared[int(text)]
                    else:
                        inline = cell.find('s:is', NS)
                        text = ''.join(t.text or '' for t in inline.findall('.//s:t', NS)) if inline is not None else None
                    cells[cell.attrib['r']] = text
                rows.append(cells)
            sheets.append({'name': name, 'rows': rows})
        comments = []
        for name in archive.namelist():
            if 'comments' in name.lower() and name.endswith('.xml'):
                root = ET.fromstring(archive.read(name))
                comments.extend({'cell': c.attrib.get('ref'), 'text': ''.join(c.itertext())}
                                for c in root.findall('s:commentList/s:comment', NS))
    return {'sha256': sha256(path.read_bytes()).hexdigest(), 'sheets': sheets,
            'comments': comments, 'scope': 'read_only_official_template_not_an_import_test'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    print(json.dumps(inspect_template(parser.parse_args().path), ensure_ascii=False, indent=2))
