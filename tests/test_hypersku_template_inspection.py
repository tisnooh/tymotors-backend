"""In-memory ZIP fixtures only: no workbook writes, upload, API or network."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import tools.inspect_hypersku_template as tool

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HEADERS = ('SKU Code', 'Store ID', 'Order Number', 'Hypersku Quantity', 'First Name',
           'Last Name', 'Address1', 'Address2', 'City', 'Province', 'Country', 'Zip',
           'Phone Number', 'Email', 'POD Text', 'POD Image')
STOCK_HEADERS = ('SKU Code', 'Hypersku Quantity')


def text_cell(reference, text):
    return f'<c r="{reference}" t="inlineStr"><is><t>{escape(text)}</t></is></c>'


def package(*, headers=HEADERS, extra_rows='', extra_sheet=None, extra_members=None,
            target='worksheets/sheet7.xml', external=False, header_xml=None,
            shared=None, sheet_name='Fixture', sheet_state=None, workbook_extra=''):
    if header_xml is None:
        header_xml=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(headers))
    state='' if sheet_state is None else f' state="{sheet_state}"'
    sheets=f'<sheet name="{escape(sheet_name)}" sheetId="7" r:id="rId7"{state}/>'
    if extra_sheet is not None:
        sheets+='<sheet name="SYNTHETIC-PRIVATE-SHEET" sheetId="8" r:id="rId8" state="hidden"/>'
    mode=' TargetMode="External"' if external else ''
    relationships=f'<Relationships><Relationship Id="rId7" Target="{escape(target)}"{mode}/>'
    if extra_sheet is not None:relationships+='<Relationship Id="rId8" Target="worksheets/sheet8.xml"/>'
    members={
        'xl/workbook.xml':f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheets}</sheets>{workbook_extra}</workbook>',
        'xl/_rels/workbook.xml.rels':relationships+'</Relationships>',
        'xl/worksheets/sheet7.xml':f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">{header_xml}</row>{extra_rows}</sheetData></worksheet>',
    }
    if extra_sheet is not None:
        members['xl/worksheets/sheet8.xml']=f'<worksheet xmlns="{MAIN}"><sheetData>{extra_sheet}</sheetData></worksheet>'
    if shared is not None:
        members['xl/sharedStrings.xml']=f'<sst xmlns="{MAIN}">'+''.join('<si><t>'+escape(text)+'</t></si>' for text in shared)+'</sst>'
    members.update(extra_members or {})
    result=BytesIO()
    with ZipFile(result,'w',compression=ZIP_DEFLATED) as archive:
        for name,content in members.items():archive.writestr(name,content)
    return result.getvalue()


def inspect_bytes(data, *, kind='customer-order'):
    source=BytesIO(data)
    with patch.object(tool,'Path',return_value=SimpleNamespace(open=lambda mode:source)):
        return tool.inspect_template('never-opened-virtual-path', kind=kind)


def refuse(data, code=None, *, kind='customer-order'):
    with pytest.raises(tool.TemplateInspectionError) as raised:inspect_bytes(data, kind=kind)
    if code is not None:assert str(raised.value)==code
    assert 'SYNTHETIC-PRIVATE' not in str(raised.value)
    assert raised.value.__suppress_context__


def test_exact_header_only_contract_hash_and_no_sheet_name_output():
    data=package(sheet_name='SYNTHETIC-PRIVATE-SHEET-NAME')
    with ZipFile(BytesIO(data)) as z:expanded=sum(i.file_size for i in z.infolist())
    result=inspect_bytes(data)
    assert result=={'sha256':sha256(data).hexdigest(),'kind':'customer-order','headers':list(HEADERS),
        'sheet_count':1,'rows_scanned':1,'cells_scanned':16,'comment_count':0,
        'zip_member_count':3,'expanded_bytes':expanded,'scope':'read_only_header_only_not_an_import_test'}
    assert tool.EXPECTED_HEADERS==HEADERS
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(result)


def test_actual_relationship_shared_strings_and_rich_text_headers():
    cells='<c r="A1" t="s"><v>0</v></c>'
    cells+='<c r="B1" t="inlineStr"><is><r><t>Store </t></r><r><t>ID</t></r></is></c>'
    cells+=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(HEADERS) if i>1)
    assert inspect_bytes(package(header_xml=cells,shared=['SKU Code']))['headers']==list(HEADERS)


@pytest.mark.parametrize('headers',[HEADERS[:-1],HEADERS+('PRIVATE',),HEADERS[::-1],
    ('sku code',)+HEADERS[1:],('SKU Code ',)+HEADERS[1:],('SYNTHETIC-PRIVATE-EMAIL',)+HEADERS[1:]])
def test_missing_extra_reordered_or_arbitrary_headers_refused(headers):
    refuse(package(headers=headers),'template_header_mismatch')


@pytest.mark.parametrize('number',[2,8,9,100,1_048_576])
@pytest.mark.parametrize('cell',[
    '<c r="A{n}" t="inlineStr"><is><t>SYNTHETIC-PRIVATE-CUSTOMER</t></is></c>',
    '<c r="P{n}" t="str"><v>SYNTHETIC-PRIVATE-CUSTOMER</v></c>',
    '<c r="A{n}"><v>0</v></c>', '<c r="A{n}" t="b"><v>0</v></c>',
    '<c r="A{n}" t="inlineStr"><is><t> </t></is></c>',
])
def test_customer_data_refused_on_all_rows(number,cell):
    refuse(package(extra_rows=f'<row r="{number}">'+cell.format(n=number)+'</row>'),
           'template_customer_data_not_allowed')


@pytest.mark.parametrize('number',[1,2,9,1000])
@pytest.mark.parametrize('formula',['<f>SYNTHETIC-PRIVATE-FORMULA</f>','<f/>',
    '<f>1+1</f><v>2</v>','<f t="shared" si="0"/><v>0</v>'])
def test_formula_with_or_without_cached_value_refused(number,formula):
    if number==1:
        header=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(HEADERS))
        data=package(header_xml=header.replace('</c>',formula+'</c>',1))
    else:data=package(extra_rows=f'<row r="{number}"><c r="A{number}">{formula}</c></row>')
    refuse(data,'template_formula_not_allowed')


@pytest.mark.parametrize('extra,code',[
    ('','template_single_sheet_required'),
    ('<row r="9">'+text_cell('A9','SYNTHETIC-PRIVATE-EXTRA-SHEET')+'</row>', 'template_single_sheet_required'),
    ('<row r="9"><c r="A9"><f>1+1</f><v>2</v></c></row>', 'template_formula_not_allowed'),
])
def test_extra_hidden_sheet_refused_even_when_empty(extra,code):
    refuse(package(extra_sheet=extra),code)


@pytest.mark.parametrize('path',['xl/worksheets/orphan.xml','unusual/unlisted.xml'])
def test_unlisted_orphan_worksheet_refused(path):
    orphan=f'<worksheet xmlns="{MAIN}"><sheetData><row r="9">{text_cell("A9","SYNTHETIC-PRIVATE-ORPHAN")}</row></sheetData></worksheet>'
    refuse(package(extra_members={path:orphan}),'template_extra_worksheet_not_allowed')


def test_comments_are_only_counted_no_author_text_or_reference():
    comments=f'<comments xmlns="{MAIN}"><authors><author>SYNTHETIC-PRIVATE-AUTHOR</author></authors><commentList><comment ref="SYNTHETIC-PRIVATE-REF"><text><t>SYNTHETIC-PRIVATE-COMMENT</t></text></comment></commentList></comments>'
    result=inspect_bytes(package(extra_members={'xl/comments1.xml':comments}))
    assert result['comment_count']==1
    assert 'SYNTHETIC-PRIVATE' not in json.dumps(result)
    assert 'comments' not in result and 'sheets' not in result


@pytest.mark.parametrize('target,external',[('../customer.xml',False),('https://example.test/sheet.xml',True),
    ('https://example.test/sheet.xml',False),('file:///private.xml',False),('\\\\server\\share',False)])
def test_invalid_targets_never_fetch_or_extract(target,external):
    refuse(package(target=target,external=external))


def test_external_relationship_outside_workbook_refused():
    rel='<Relationships><Relationship Id="rId1" Target="https://example.test/private" TargetMode="External"/></Relationships>'
    refuse(package(extra_members={'xl/worksheets/_rels/sheet7.xml.rels':rel}),
           'template_external_relationship_not_allowed')


def test_unused_private_shared_strings_refused():
    refuse(package(shared=['SYNTHETIC-PRIVATE-DELETED-ROW']),'template_non_header_shared_string')


@pytest.mark.parametrize('state',['hidden','veryHidden'])
def test_only_visible_authorized_sheet_allowed(state):
    refuse(package(sheet_state=state),'template_visible_sheet_required')


def test_empty_formatted_cells_allowed_and_counted():
    rows='<row r="9"><c r="A9" s="1"/><c r="P9" t="inlineStr"><is><t/></is></c></row>'
    result=inspect_bytes(package(extra_rows=rows))
    assert result['rows_scanned']==2 and result['cells_scanned']==18


@pytest.mark.parametrize('row',[
    '<row r="1"/>','<row r="02"/>','<row r="0"/>','<row r="1048577"/>',
    '<row r="2"><c r="A9"/></row>','<row r="2"><c r="A2"/><c r="A2"/></row>',
    '<row r="2"><c r="A2"><v>0</v><v>1</v></c></row>',
    '<row r="2"><c r="A2"><v>0</v><is><t/></is></c></row>',
    '<row r="2"><c r="A2">SYNTHETIC-PRIVATE-DIRECT-TEXT</c></row>',
    '<row r="2">SYNTHETIC-PRIVATE-ROW-TEXT</row>',
    '<row r="2"><c r="A2"><unknown>SYNTHETIC-PRIVATE-TEXT</unknown></c></row>',
    '<row r="2"><c r="A2"><v/>SYNTHETIC-PRIVATE-TAIL</c></row>',
])
def test_malformed_rows_cells_and_duplicates_refused(row):
    refuse(package(extra_rows=row))


@pytest.mark.parametrize('index',['-1','999','PRIVATE','0.5'])
def test_invalid_shared_string_indices_refused(index):
    cells='<c r="A1" t="s"><v>'+index+'</v></c>'
    cells+=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(HEADERS) if i)
    refuse(package(header_xml=cells,shared=['SKU Code']),'template_invalid_shared_string')


def test_numeric_header_type_does_not_masquerade_as_text_contract():
    cells='<c r="A1" t="n"><v>SKU Code</v></c>'
    cells+=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(HEADERS) if i)
    refuse(package(header_xml=cells),'template_invalid_header_cell_type')


def test_duplicate_zip_member_names_are_refused():
    data=BytesIO(package())
    with pytest.warns(UserWarning,match='Duplicate name'):
        with ZipFile(data,'a') as archive:archive.writestr('xl/workbook.xml','<PRIVATE/>')
    refuse(data.getvalue(),'template_invalid_zip_members')


def test_defined_name_formula_refused():
    refuse(package(workbook_extra='<definedNames><definedName name="PRIVATE">1+1</definedName></definedNames>'),
           'template_formula_not_allowed')


@pytest.mark.parametrize('extra',[
    '<conditionalFormatting sqref="A2"><cfRule type="expression" priority="1"><formula>1+1</formula></cfRule></conditionalFormatting>',
    '<dataValidations count="1"><dataValidation type="whole" sqref="A2"><formula1>1</formula1></dataValidation></dataValidations>',
    '<dataValidations count="1"><dataValidation type="whole" sqref="A2"><formula2>9</formula2></dataValidation></dataValidations>',
])
def test_conditional_formatting_and_validation_formulas_refused(extra):
    headers=''.join(text_cell(chr(65+i)+'1',value) for i,value in enumerate(HEADERS))
    worksheet=f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">{headers}</row></sheetData>{extra}</worksheet>'
    refuse(package(extra_members={'xl/worksheets/sheet7.xml':worksheet}),
           'template_formula_not_allowed')


@pytest.mark.parametrize('member,xml',[
    ('xl/tables/table1.xml',f'<table xmlns="{MAIN}"><tableColumns><tableColumn><calculatedColumnFormula>1+1</calculatedColumnFormula></tableColumn></tableColumns></table>'),
    ('xl/tables/table1.xml',f'<table xmlns="{MAIN}"><tableColumns><tableColumn><totalsRowFormula>1+1</totalsRowFormula></tableColumn></tableColumns></table>'),
    ('xl/charts/chart1.xml','<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:f>Sheet1!A1</c:f></c:chart></c:chartSpace>'),
    ('xl/charts/chart1.xml','<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:formula>1+1</c:formula></c:chart></c:chartSpace>'),
])
def test_table_and_chart_formula_xml_outside_worksheet_refused(member,xml):
    refuse(package(extra_members={member:xml}),'template_formula_not_allowed')


@pytest.mark.parametrize('tag',['f','formula','formula1','formula2','calculatedColumnFormula','totalsRowFormula','definedName'])
def test_known_formula_elements_in_any_xml_part_refused_even_empty(tag):
    xml=f'<root xmlns="urn:synthetic"><{tag}/></root>'
    refuse(package(extra_members={'xl/otherwise-unused.xml':xml}),
           'template_formula_not_allowed')


@pytest.mark.parametrize('encoding',['utf-8','utf-16','utf-32'])
def test_dtd_and_entities_never_expanded(encoding):
    xml='<?xml version="1.0" encoding="'+encoding+'"?><!DOCTYPE x [<!ENTITY hidden "SYNTHETIC-PRIVATE-ENTITY">]><x>&hidden;</x>'
    refuse(package(extra_members={'xl/extra.xml':xml.encode(encoding)}),'template_xml_declaration_not_allowed')


def test_invalid_zip_xml_and_io_errors_redacted():
    refuse(b'SYNTHETIC-PRIVATE-NOT-A-ZIP','template_invalid_package')
    refuse(package(extra_members={'xl/extra.xml':'<SYNTHETIC-PRIVATE-INVALID'}),'template_invalid_package')
    virtual=SimpleNamespace(open=lambda mode:(_ for _ in ()).throw(OSError('SYNTHETIC-PRIVATE-PATH')))
    with patch.object(tool,'Path',return_value=virtual):
        with pytest.raises(tool.TemplateInspectionError,match='^template_invalid_package$'):tool.inspect_template('unused')


def test_limits_file_expanded_members_nodes_rows_cells(monkeypatch):
    refuse(b'x'*(1024*1024+1),'template_file_size_limit')
    refuse(package(extra_members={'large.bin':b'x'*(10*1024*1024+1)}),'template_expanded_size_limit')
    refuse(package(extra_members={f'extra/{i}.bin':b'' for i in range(254)}),'template_invalid_zip_members')
    with monkeypatch.context() as m:
        m.setattr(tool,'_MAX_XML_NODES',1);refuse(package(),'template_xml_node_limit')
    with monkeypatch.context() as m:
        m.setattr(tool,'_MAX_ROWS',1);refuse(package(extra_rows='<row r="9"/>'),'template_row_limit')
    with monkeypatch.context() as m:
        m.setattr(tool,'_MAX_CELLS',15);refuse(package(),'template_cell_limit')


def test_cli_failure_only_prints_safe_code(capsys):
    data=package(extra_rows='<row r="9">'+text_cell('A9','SYNTHETIC-PRIVATE-CUSTOMER')+'</row>')
    with patch.object(tool,'Path',return_value=SimpleNamespace(open=lambda mode:BytesIO(data))):
        with pytest.raises(SystemExit) as raised:tool.main(['SYNTHETIC-PRIVATE-PATH'])
    assert raised.value.code==2
    output=capsys.readouterr()
    assert output.out=='' and output.err=='Inspection refused: template_customer_data_not_allowed\n'


def test_official_download_accepted_and_source_bytes_unchanged():
    path=Path(r'C:\Users\utilisateur\Downloads\HyperskuExcelOrderTemplate.xlsx')
    if not path.is_file():pytest.skip('Official manually downloaded source is unavailable on this host')
    before=path.read_bytes()
    result=tool.inspect_template(path)
    assert result['sha256']==sha256(before).hexdigest()=='c3fc64e82777c17b0882971138a1560fe7e5c1b690a398f11a513a093e63ad4b'
    assert result['headers']==list(HEADERS)
    assert result['sheet_count']==1 and result['rows_scanned']==1 and result['cells_scanned']==16
    assert result['comment_count']==0 and path.read_bytes()==before


def test_stock_contract_is_explicit_and_does_not_infer_customer_order_fields():
    result=inspect_bytes(package(headers=STOCK_HEADERS),kind='inbound-stock')
    assert result['kind']=='inbound-stock' and result['headers']==list(STOCK_HEADERS)
    assert result['cells_scanned']==2 and result['rows_scanned']==1
    assert 'Store ID' not in result['headers']
    assert tool.INBOUND_STOCK_HEADERS==STOCK_HEADERS


def test_stock_model_refused_under_default_customer_contract_and_inverse():
    refuse(package(headers=STOCK_HEADERS),'template_header_mismatch')
    refuse(package(headers=HEADERS),'template_header_mismatch',kind='inbound-stock')


@pytest.mark.parametrize('kind',[None,[],1,True,'auto','stock','SYNTHETIC-PRIVATE-KIND'])
def test_unknown_kind_is_fixed_error_before_read(kind):
    with patch.object(tool,'Path') as path:
        with pytest.raises(tool.TemplateInspectionError,match='^template_unknown_kind$'):
            tool.inspect_template('unused',kind=kind)
        path.assert_not_called()


@pytest.mark.parametrize('row',[
    '<row r="9">'+text_cell('B9','SYNTHETIC-PRIVATE-DATA')+'</row>',
    '<row r="1000"><c r="A1000"><f>1+1</f><v>2</v></c></row>',
])
def test_stock_contract_uses_same_full_sheet_data_and_formula_guards(row):
    refuse(package(headers=STOCK_HEADERS,extra_rows=row),kind='inbound-stock')


def test_stock_contract_rejects_other_headers_and_extra_sheet():
    refuse(package(headers=('SKU Code','Store ID')),kind='inbound-stock')
    refuse(package(headers=STOCK_HEADERS,extra_sheet=''),kind='inbound-stock')
    refuse(package(headers=STOCK_HEADERS,shared=['Store ID']),kind='inbound-stock')


def test_cli_can_explicitly_select_stock_contract(capsys):
    data=package(headers=STOCK_HEADERS)
    with patch.object(tool,'Path',return_value=SimpleNamespace(open=lambda mode:BytesIO(data))):
        tool.main(['unused','--kind','inbound-stock'])
    result=json.loads(capsys.readouterr().out)
    assert result['kind']=='inbound-stock' and result['headers']==list(STOCK_HEADERS)


def test_real_stock_download_accepted_only_for_stock_and_bytes_unchanged():
    path=Path(r'C:\Users\utilisateur\Downloads\HyperskuExcelStockOrderTemplate.xlsx')
    if not path.is_file():pytest.skip('Official manually downloaded stock source is unavailable on this host')
    before=path.read_bytes()
    result=tool.inspect_template(path,kind='inbound-stock')
    assert result['sha256']==sha256(before).hexdigest()=='8ebd1166dc196462f8025cb742a827e4f30ec2a64254d706565fa82676fbfe78'
    assert result['kind']=='inbound-stock' and result['headers']==list(STOCK_HEADERS)
    assert result['sheet_count']==1 and result['rows_scanned']==1 and result['cells_scanned']==2
    assert result['comment_count']==0
    with pytest.raises(tool.TemplateInspectionError):tool.inspect_template(path)
    assert path.read_bytes()==before
