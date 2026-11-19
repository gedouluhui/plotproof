"""Command line entry points: ``plotproof demo`` and ``plotproof check``."""
from __future__ import annotations

import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

from .export import CheckError, CheckReport, check_figure, render_html


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def _save(report: CheckReport, json_path: str | None, html_path: str | None) -> None:
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True) + '\n'
    if json_path:
        _write(Path(json_path), payload)
    else:
        sys.stdout.write(payload)
    if html_path:
        _write(Path(html_path), render_html(report))


def _load_figure(module_path: str, factory: str):
    path = Path(module_path).resolve()
    if not path.is_file():
        raise SystemExit('no such file: %s' % path)
    spec = spec_from_file_location('plotproof_user_figure', path)
    if spec is None or spec.loader is None:
        raise SystemExit('cannot import %s' % path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    build = getattr(module, factory, None)
    if not callable(build):
        raise SystemExit('%s has no callable %s()' % (path.name, factory))
    return build()


def _demo_figure(deliberate: bool):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4, 3), dpi=100, layout='constrained')
    ax.bar(['alpha', 'beta', 'gamma'], [3, 5, 2])
    ax.set_xlabel('Category')
    ax.set_ylabel('Count', rotation=0)
    ax.set_title('PlotProof demo' if not deliberate else 'PlotProof demo (clipped)')
    if deliberate:
        # A real defect: the label starts inside the page and runs past the
        # right edge, so most of its characters are painted outside.
        fig.text(0.96, 0.55, 'This annotation runs past the edge', ha='left', va='center')
    return fig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='plotproof',
                                     description='Source-assisted export evidence for Matplotlib figures.')
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='run a clean and a deliberately clipped sample')
    demo.add_argument('--output', default='plotproof-demo', help='directory for reports')
    check = sub.add_parser('check', help='check a figure built by a Python file')
    check.add_argument('module', help='path to a .py file exposing figure()')
    check.add_argument('--factory', default='figure', help='callable returning a Figure (default: figure)')
    check.add_argument('--json', dest='json_path', default=None)
    check.add_argument('--html', dest='html_path', default=None)
    args = parser.parse_args(argv)

    if args.command == 'demo':
        output = Path(args.output)
        status = 0
        for name, deliberate in (('clean', False), ('clipped', True)):
            report = check_figure(_demo_figure(deliberate))
            _save(report, str(output / (name + '.json')), str(output / (name + '.html')))
            print('%s: %s' % (name, report.state))
            if deliberate and report.state != 'FAIL':
                print('the deliberate sample did not produce a finding', file=sys.stderr)
                status = 1
        return status

    try:
        fig = _load_figure(args.module, args.factory)
    except CheckError as error:
        print('check failed: %s' % error.reason, file=sys.stderr)
        return 2
    report = check_figure(fig)
    _save(report, args.json_path, args.html_path)
    return 1 if report.state == 'FAIL' else 0
