#!/usr/bin/env python3
"""Python 3.9+，仅标准库。init 建任务；finalize 校验并发布模型准备的脚本。"""
import argparse
import ast
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import tokenize
from datetime import datetime
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / 'references/upcf-evaluation.md'
BLOCKED = {'source_missing', 'source_ambiguous', 'no_candidate', 'insufficient_evidence', 'static_failed'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not inside(path, root):
        raise ValueError('路径越界: ' + str(relative))
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], encoding='utf-8', errors='replace').strip()


def config(reference):
    blocks = re.findall(r'^```json\s*\n(.*?)^```', reference.read_text(encoding='utf-8-sig'), re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('reference 必须包含唯一 JSON 配置块')
    cfg = json.loads(blocks[0])
    for key in ('repository_root', 'cases_root', 'experience_jsonl', 'output_root'):
        if not cfg.get(key) or not Path(cfg[key]).is_absolute():
            raise ValueError('请填写绝对路径: ' + key)
    repo, cases, output = (Path(cfg[k]).resolve() for k in ('repository_root', 'cases_root', 'output_root'))
    if not repo.is_dir() or not cases.is_dir() or cases != repo / 'Cases':
        raise ValueError('cases_root 必须是 repository_root 下的 Cases 目录')
    if inside(output, repo) or inside(repo, output):
        raise ValueError('输出根目录必须与源仓库分离，且不能是仓库的祖先目录')
    if cfg.get('expected_count') != 23 or cfg.get('candidate_scope') != 'same_directory':
        raise ValueError('本版固定尝试 23 条，候选范围为 same_directory')
    for value in cfg.get('readonly_reference_paths', []):
        if not inside(Path(value), repo):
            raise ValueError('只读参考路径必须位于仓库内')
    return cfg


def init(reference):
    cfg = config(reference)
    repo, cases = Path(cfg['repository_root']).resolve(), Path(cfg['cases_root']).resolve()
    records = []
    for line in Path(cfg['experience_jsonl']).read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            records.append(json.loads(line))
    if len(records) != 23:
        raise ValueError('需要 prepare_upcf_evaluation.py 输出的 23 行扁平 JSONL')
    for key in ('sequence', 'case_id', 'doc_id'):
        if len({r[key] for r in records}) != 23:
            raise ValueError('缺少或重复字段: ' + key)
    if sorted(r['sequence'] for r in records) != list(range(1, 24)):
        raise ValueError('sequence 必须为 1 至 23')
    for r in records:
        for key in ('case_id', 'doc_id', 'title', 'experience'):
            if not isinstance(r.get(key), str) or not r[key].strip():
                raise ValueError('无效字段: ' + key)
        found = re.findall(r'^来源用例：[ \t]*([^\r\n]+)', r['experience'], re.M)
        if len(found) != 1 or found[0].strip() != r['case_id']:
            raise ValueError('来源用例与正文不一致: ' + r['doc_id'])
    files = sorted(p for p in cases.rglob('*.py') if p.is_file() and inside(p, cases))
    tasks = []
    for r in sorted(records, key=lambda r: r['sequence']):
        matches = [p for p in files if p.stem == r['case_id']]
        task = dict(r, source_paths=[str(p.relative_to(repo)) for p in matches], candidates=[], status='pending')
        if len(matches) != 1:
            task.update(status='source_missing' if not matches else 'source_ambiguous', reason='按文件名定位来源不唯一；需要人工核对，不猜测来源')
        else:
            task['candidates'] = [str(p.relative_to(repo)) for p in files if p.parent == matches[0].parent and p != matches[0]]
            if not task['candidates']:
                task.update(status='no_candidate', reason='同目录没有其他 Python 用例')
        tasks.append(task)
    manifest = dict(config=cfg, repository_commit=git(repo, 'rev-parse', 'HEAD'),
                    repository_status=git(repo, 'status', '--porcelain'),
                    input_sha256=digest(Path(cfg['experience_jsonl'])),
                    case_hashes={str(p.relative_to(repo)): digest(p) for p in files},
                    reference_hashes={str(p.relative_to(repo)): digest(p)
                        for folder in cfg.get('readonly_reference_paths', [])
                        for p in Path(folder).rglob('*') if p.is_file() and inside(p, repo)}, tasks=tasks)
    run = Path(cfg['output_root']) / ('run_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    run.mkdir(parents=True, exist_ok=False)
    (run / 'evaluator/staging').mkdir(parents=True)
    save_json(run / 'evaluator/manifest.json', manifest)
    print(str(run.resolve()))


def source_text(path):
    with tokenize.open(str(path)) as stream:
        return stream.read()


def structure(text, name):
    tree = ast.parse(text)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    if len(classes) != 1:
        raise ValueError('类名必须与文件名一致: ' + name)
    cls = classes[0]
    if not any(isinstance(n, ast.Name) and n.id == 'CloudSpider' for b in cls.bases for n in ast.walk(b)):
        raise ValueError('必须继承 CloudSpider')
    methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for required in ('__init__', 'Precondition', 'Procedure', 'Failure', 'Postcondition'):
        if required not in methods:
            raise ValueError('缺少方法: ' + required)
    if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'BackUpDebugLog' for n in ast.walk(methods['Failure'])):
        raise ValueError('Failure 缺少 BackUpDebugLog 调用')
    decorators = [d for d in methods['__init__'].decorator_list if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == 'information']
    if len(decorators) != 1:
        raise ValueError('缺少唯一 information 装饰器')
    keywords = {k.arg: k.value for k in decorators[0].keywords}
    if not {'CaseID', 'CaseName', 'Level'} <= keywords.keys() or not isinstance(keywords['CaseID'], ast.Constant) or keywords['CaseID'].value != name:
        raise ValueError('CaseID 或 information 字段不符合要求')
    return tree


def finalize(run):
    for child in ('evaluator', 'evaluator/staging', 'evaluator/patches', 'evaluator/baselines', 'evaluation_cases'):
        safe(run, child)
    manifest_path = run / 'evaluator/manifest.json'
    manifest = read_json(manifest_path)
    repo = Path(manifest['config']['repository_root']).resolve()
    if inside(run, repo):
        raise ValueError('运行目录不能在源仓库内')
    if git(repo, 'rev-parse', 'HEAD') != manifest['repository_commit'] or git(repo, 'status', '--porcelain') != manifest['repository_status']:
        raise ValueError('源仓库版本或工作区状态已变化，请重新初始化')
    for relative, sha in {**manifest['case_hashes'], **manifest.get('reference_hashes', {})}.items():
        if digest(safe(repo, relative)) != sha:
            raise ValueError('Cases 内容已变化: ' + relative)
    decisions = read_json(run / 'evaluator/decisions.json')
    if not isinstance(decisions, list) or len(decisions) != 23 or {d['sequence'] for d in decisions} != set(range(1, 24)):
        raise ValueError('decisions 必须逐条覆盖 1 至 23，不得重复或遗漏')
    decisions = {d['sequence']: d for d in decisions}
    used, names, prepared = set(), set(), []
    for task in manifest['tasks']:
        d = decisions[task['sequence']]
        if d.get('status') in BLOCKED:
            if not d.get('reason', '').strip():
                raise ValueError('阻塞项必须填写原因')
            task.update(result=d)
            continue
        try:
            if d.get('status') != 'ready' or task['status'] != 'pending':
                raise ValueError('只有来源明确的 pending 任务可以生成')
            candidate = d['candidate']
            if candidate not in task['candidates'] or candidate in used:
                raise ValueError('候选不在同目录清单或已使用')
            mother = safe(repo, candidate)
            if digest(mother) == digest(safe(repo, task['source_paths'][0])):
                raise ValueError('候选与来源脚本内容完全相同')
            name = d['new_case_id']
            if (not name.isidentifier() or name.upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}
                    or name.casefold() in names or any(Path(p).stem.casefold() == name.casefold() for p in manifest['case_hashes'])):
                raise ValueError('新 CaseID 不合法或冲突')
            for key in ('selection_reason', 'injection_reason', 'expected_failure', 'acceptance', 'manual_checks'):
                if not isinstance(d.get(key), str) or not d[key].strip():
                    raise ValueError('缺少分析字段: ' + key)
            texts = []
            for key in ('baseline', 'faulty'):
                p = safe(run / 'evaluator/staging', d[key])
                text = source_text(p)
                structure(text, name)
                texts.append(text)
            baseline, faulty = texts
            # 基线只能修改标识，不能顺手修复或删除母本业务逻辑。
            expected = source_text(mother).replace(mother.stem, name)
            if baseline != expected:
                raise ValueError('基线必须仅将母本旧标识替换为新标识，其余内容不变')
            if baseline == faulty:
                raise ValueError('没有注入修改')
            with mother.open('rb') as stream:
                encoding, _ = tokenize.detect_encoding(stream.readline)
            baseline.encode(encoding)
            faulty.encode(encoding)
            relative = Path(candidate).relative_to('Cases').with_name(name + '.py')
            prepared.append((task, d, relative, baseline, faulty))
            used.add(candidate)
            names.add(name.casefold())
            task['result'] = dict(d, status='generated_pending_execution', runtime_verified=False)
        except (ValueError, KeyError, SyntaxError, UnicodeError, OSError) as exc:
            task['result'] = dict(status='static_failed', reason=str(exc), runtime_verified=False)
    # 不覆盖先前结果。先检查全部目标，再写入。
    if any((run / p).exists() for p in ('evaluation_cases', 'evaluator/baselines', 'evaluator/patches')):
        raise ValueError('本次结果已发布；重新 init，不能覆盖已有生成结果')
    original_manifest = manifest_path.read_bytes()
    try:
        for task, d, relative, baseline, faulty in prepared:
            for root, text in [('evaluation_cases', faulty), ('evaluator/baselines', baseline)]:
                path = safe(run, str(Path(root) / relative))
                path.parent.mkdir(parents=True, exist_ok=True)
                # 保留源文件编码声明对应的编码，不更改字符串内容。
                with safe(repo, d['candidate']).open('rb') as stream:
                    encoding, _ = tokenize.detect_encoding(stream.readline)
                with path.open('w', encoding=encoding, newline='') as stream:
                    stream.write(text)
            patch_dir = run / 'evaluator/patches'
            patch_dir.mkdir(exist_ok=True)
            for label, before, after in [('inject', baseline, faulty), ('repair', faulty, baseline)]:
                patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=str(relative), tofile=str(relative)))
                (patch_dir / ('%02d_%s.diff' % (task['sequence'], label))).write_text(patch, encoding='utf-8')
            task['result']['output_path'] = str(Path('evaluation_cases') / relative)
        save_json(manifest_path, manifest)
        report = ['# 评测集生成报告', '', '仓库提交: ' + manifest['repository_commit'], '', '所有生成项均未执行；预期故障不是实际日志。', '']
        for t in manifest['tasks']:
            report.extend(['## %s. %s' % (t['sequence'], t['case_id']), '', json.dumps(t['result'], ensure_ascii=False, indent=2), ''])
        (run / 'evaluator/report.md').write_text('\n'.join(report), encoding='utf-8')
    except (OSError, UnicodeError, ValueError):
        for relative in ('evaluation_cases', 'evaluator/baselines', 'evaluator/patches'):
            path = safe(run, relative)
            if path.exists():
                shutil.rmtree(path)
        manifest_path.write_bytes(original_manifest)
        raise
    print('GENERATED: %s / TOTAL: 23 / RUNTIME_VERIFIED: 0' % len(prepared))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('init')
    start.add_argument('--reference', type=Path, default=REFERENCE)
    finish = sub.add_parser('finalize')
    finish.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        init(args.reference) if args.command == 'init' else finalize(args.run_dir.resolve())
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'ERROR: %s\n' % exc)


if __name__ == '__main__':
    main()
