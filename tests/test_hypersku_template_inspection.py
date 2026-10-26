"""No import/upload: tiny ZIP fixtures test the read-only template inspector."""
from zipfile import ZipFile
import pytest
from tools.inspect_hypersku_template import inspect_template

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def fixture(tmp_path, target='worksheets/sheet7.xml', external=False):
    path = tmp_path / 'synthetic.xlsx'
    with ZipFile(path, 'w') as archive:
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Fixture" sheetId="7" r:id="rId7"/></sheets></workbook>')
        mode = ' TargetMode="External"' if external else ''
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships><Relationship Id="rId7" Target="{target}"{mode}/></Relationships>')
        archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{MAIN}"><si><t>SKU Code</t></si></sst>')
        archive.writestr('xl/worksheets/sheet7.xml', f'<worksheet xmlns="{MAIN}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Store ID</t></is></c></row></sheetData></worksheet>')
    return path


def test_actual_relationship_not_guessed_sheet_number(tmp_path):
    path = fixture(tmp_path)
    before = path.read_bytes()
    result = inspect_template(path)
    assert result['sheets'] == [{'name': 'Fixture', 'rows': [{'A1': 'SKU Code', 'B1': 'Store ID'}]}]
    assert len(result['sha256']) == 64
    assert path.read_bytes() == before


@pytest.mark.parametrize('target,external', [('../customer.xml', False), ('https://example.test/sheet.xml', True)])
def test_invalid_targets_never_fetch_or_extract(tmp_path, target, external):
    with pytest.raises(ValueError):
        inspect_template(fixture(tmp_path, target, external))


def test_oversize_template_refused_before_zip_read(tmp_path):
    path = tmp_path / 'oversized.xlsx'
    path.write_bytes(b'x' * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match='small provider template'):
        inspect_template(path)
