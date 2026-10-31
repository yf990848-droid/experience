#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""导出指定的 23 条 UPCF 经验，供评测集生成 skill 使用（Python 3.9+，仅标准库）。

在项目根目录运行：python evaluation/prepare_upcf_evaluation.py
也可指定：python evaluation/prepare_upcf_evaluation.py --input INPUT.jsonl --output-dir OUTPUT
默认读取用户的 20261022 导出文件，在其旁新建 evaluation_input_时间戳 目录。
不联网、不修改输入；输入顺序不影响选择。缺失/重复 ID 或来源不符则报错退出。
JSONL 每行是扁平对象：sequence、original_sequence、case_id、doc_id、title、
summary、experience、scene_id、scene、product、metadata、rag_search_text 等。
完整保留原经验正文（含 Diff），不保留向量；不按质量或执行结果进一步过滤。
Excel 仅包含：新序号、用例编号、经验title、经验doc_id。
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

DEFAULT_INPUT = Path(
    r'D:\agent-memory\AgentMemory\exports\UPCF_20261022_114414_275069'
    r'\UPCF_experiences_filtered.jsonl'
)
# 原序号仅用于溯源，实际按固定 doc_id 选择，并校验对应的来源用例。
# 对应 evaluation/UPCF_experiences_filtered.md（2026-10-24 确认的清单）。
SELECTION = [
    (2, 'tracefix_7ad067385c316e063c19115bc741f5d1197aeadef8c3af27', 'Network_SCP_N5_01_04'),
    (4, 'tracefix_95b427c272edd5ed4e827e02bee418ca741950c83e56fb08', 'Nx_Nz_Function_31_13'),
    (5, 'tracefix_b1e4f25b6c11e10e9d6edb161a55af783e3ca8943dfd1dc0', 'PCF_N23If_Msg_qosShortGuarantee_01_14'),
    (6, 'tracefix_d3064d6efb1c0a8095480f5d25cd62e502c9b27653f5f94f', 'PCF_NCS_Rel_Subscribe_01_08'),
    (9, 'tracefix_b5917c1c94f377d6142fda2b6e979cf1523a82a9fd6460d5', 'Network_SCP_N24_Hpcf_01_10'),
    (10, 'tracefix_45d85048aba79de606fe520aea3b4fa95a39b04269476454', 'Network_SCP_Srv_04_54'),
    (11, 'tracefix_9cafcb1146662e428eae198c356079b35aca900165b882c9', 'I_14_COM_SOAP_CFG'),
    (12, 'tracefix_f3911446ae3cc9cad1b178e576199779fde044700ef06afd', 'Nx_NCS_AMFReSelect_05_09'),
    (13, 'tracefix_3a04df128ce9038c500bd71ed63665300c8369ba2fdb32b3', 'IfTrace_UPCFTrace_DYETRACE_02_06'),
    (15, 'tracefix_9deca6a853fec0986675274c3c13c0a4de7852089af96b2b', 'RxIf_RxFunc_VoWiFiIP_UsrLocEnhance_27_06'),
    (16, 'tracefix_a1e0fbeb9904bd7ac9f23303c22d2d469a948e986a7bde58', 'RxIf_RxFunc_VoWiFiIP_UsrLocEnhance_27_05'),
    (17, 'tracefix_36553806ce416c963bd31961c5bdc8b24a3037d6f92c2d36', 'PCF_NCS_AISEnhanced_09_22'),
    (18, 'tracefix_23d40bd33d811202afc84ed6670d34b118cf86b4f5a6e2aa', 'PCF_NCS_NFCache_ConDis_04_02'),
    (21, 'tracefix_5a29258ac2770f1a39b8094b8490971152aed08755058b74', 'PCF_NCS_Rel_Subscribe_01_03'),
    (22, 'tracefix_4883266393b8bf96c2f1284a7aee092e658f289a2f0bd8d9', 'PCF_NCS_AISEnhanced_25_07'),
    (23, 'tracefix_9eb65e17bcc7b52335618afa5fe88e5f4a5d3a84c632262b', 'PCF_NCS_AISEnhanced_25_06'),
    (24, 'tracefix_274da91a9fa02873acc340f36bb115bd8db1d7654da1bde0', 'N24_NpcfMng_HpcfDisc_02_01'),
    (25, 'tracefix_99959a8427a2db6fda769addb1ecda8038dbd94a4eb9d87e', 'PCF_NCS_Rel_Subscribe_01_02'),
    (26, 'tracefix_bf6f3e3b83eb94b367dbfb27a7cedd75c4d05d10ff740045', 'PCF_NCS_AISEnhanced_09_21'),
    (27, 'tracefix_e0f58c951ad9b245c11c05f7b4db35eb744da0f862a8333c', 'PCF_NCS_LinkDetct_Subscribe_03_08'),
    (28, 'tracefix_c9f64fb51a0ecffc62af61e43cfe01855eb338294b4b6629', 'PCF_NCS_SrvMgt_01_07'),
    (29, 'tracefix_18294e613e1a669a33f75bc553ea95449b2a5138df00e86f', 'PCF_N23If_Mng_Discovery_02_19'),
    (30, 'tracefix_8bbb9829dccff43e1cd4f71714c89bc94605ca5f8c7d718b', 'PCF_N23If_Msg_qosShortGuarantee_01_19'),
]


def select_records(path):
    wanted = {item[1] for item in SELECTION}
    found = {}
    total = 0
    with path.open('r', encoding='utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            total += 1
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError('第 %s 行不是合法 JSON: %s' % (line_number, exc)) from exc
            if not isinstance(record, dict) or not isinstance(record.get('_source'), dict):
                raise ValueError('第 %s 行须为包含 _source 对象的 ES 导出记录' % line_number)
            source = record['_source']
            outer_id, inner_id = record.get('_id'), source.get('doc_id')
            if not isinstance(outer_id, str) or not outer_id:
                raise ValueError('第 %s 行缺少有效 _id' % line_number)
            if inner_id is not None and inner_id != outer_id:
                raise ValueError('第 %s 行 _id 与 doc_id 不一致' % line_number)
            if outer_id not in wanted:
                continue
            if outer_id in found:
                raise ValueError('选中经验 ID 重复: ' + outer_id)
            found[outer_id] = source
    missing = wanted - found.keys()
    if missing:
        raise ValueError('缺少选中经验（不会输出不完整清单）: ' + ', '.join(sorted(missing)))
    selected = []
    for sequence, (original, doc_id, expected_case) in enumerate(SELECTION, 1):
        source = found[doc_id]
        body, title = source.get('experience'), source.get('title')
        if not isinstance(body, str) or not body.strip() or not isinstance(title, str) or not title.strip():
            raise ValueError('经验正文或标题为空: ' + doc_id)
        cases = re.findall(r'^来源用例：[ \t]*([^\r\n]+)', body, re.MULTILINE)
        if len(cases) != 1 or cases[0].strip() != expected_case:
            raise ValueError('来源用例缺失、重复或不符合清单: ' + doc_id)
        item = dict(sequence=sequence, original_sequence=original,
                    case_id=expected_case, doc_id=doc_id, title=title, experience=body)
        for key in ('summary', 'scene_id', 'scene', 'product', 'metadata',
                    'rag_search_text', 'created_at', 'updated_at', 'version',
                    'quality', 'quality_category', 'quality_reason'):
            if key in source:
                item[key] = source[key]
        selected.append(item)
    if len(selected) != 23 or len({item['case_id'] for item in selected}) != 23:
        raise ValueError('必须恰好包含 23 条经验及 23 个不同来源用例')
    return selected, total


def xml_text(value):
    text = str(value)
    if len(text) > 32767 or any(
        not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF
             or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
        for c in text
    ):
        raise ValueError('Excel 单元格包含非法字符或超出长度限制')
    return escape(text)


def write_xlsx(path, records):
    """用标准库写入简单 OOXML 工作簿；文本使用 inlineStr，避免被识别为公式。"""
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rows = [('新序号', '用例编号', '经验title', '经验doc_id')]
    rows.extend((r['sequence'], r['case_id'], r['title'], r['doc_id']) for r in records)
    row_xml = []
    for number, values in enumerate(rows, 1):
        cells = []
        for column, value in zip('ABCD', values):
            ref = '%s%s' % (column, number)
            if isinstance(value, int):
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, value))
            else:
                style = '1' if number == 1 else '2'
                cells.append('<c r="%s" s="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                             % (ref, style, xml_text(value)))
        row_xml.append('<row r="%s" ht="32" customHeight="1">%s</row>' % (number, ''.join(cells)))
    sheet = ('<worksheet xmlns="%s"><dimension ref="A1:D24"/>'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
             'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
             '<cols><col min="1" max="1" width="10" customWidth="1"/>'
             '<col min="2" max="2" width="55" customWidth="1"/>'
             '<col min="3" max="3" width="60" customWidth="1"/>'
             '<col min="4" max="4" width="65" customWidth="1"/></cols>'
             '<sheetData>%s</sheetData><autoFilter ref="A1:D24"/></worksheet>') % (ns, ''.join(row_xml))
    rel_ns = 'http://schemas.openxmlformats.org/package/2006/relationships'
    office_rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%sofficeDocument" Target="xl/workbook.xml"/></Relationships>' % (rel_ns, office_rel),
        'xl/workbook.xml': '<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="经验清单" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, office_rel.rstrip('/')),
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%sworksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="%sstyles" Target="styles.xml"/></Relationships>' % (rel_ns, office_rel, office_rel),
        'xl/worksheets/sheet1.xml': sheet,
        'xl/styles.xml': '<styleSheet xmlns="%s"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF24476B"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>' % ns,
    }
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + content)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT, help='原始 ES JSONL 导出文件')
    parser.add_argument('--output-dir', type=Path, help='新输出目录，必须尚不存在')
    args = parser.parse_args()
    output_dir = None
    created = False
    try:
        records, total = select_records(args.input)
        output_dir = args.output_dir or args.input.parent / (
            'evaluation_input_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        output_dir.mkdir(parents=True, exist_ok=False)
        created = True
        jsonl = output_dir / 'UPCF_evaluation_experiences_23.jsonl'
        excel = output_dir / 'UPCF_evaluation_experiences_23.xlsx'
        with jsonl.open('w', encoding='utf-8', newline='\n') as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        write_xlsx(excel, records)
    except (OSError, ValueError) as exc:
        if created:
            shutil.rmtree(output_dir, ignore_errors=True)
        print('ERROR: %s' % exc, file=sys.stderr)
        return 1
    print('EXPORT_OK / INPUT: %s / SELECTED: 23 / UNIQUE_CASES: 23' % total)
    print('JSONL: %s' % jsonl.resolve())
    print('EXCEL: %s' % excel.resolve())
    return 0


if __name__ == '__main__':
    sys.exit(main())
