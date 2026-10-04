#!/usr/bin/env python3
"""Generate a short scenario with a local LLM and play it on StackChan and toio.

  python3 client/scenario/run.py "自己紹介してハートを作る"
  python3 client/scenario/run.py --generate-only "おやすみのあいさつ"
  python3 client/scenario/run.py --from scenarios/20261004-120000.json
  python3 client/scenario/run.py --dry-run "円になって回る"
  python3 client/scenario/run.py --interactive
"""
import argparse
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.dirname(HERE)
ROOT = os.path.dirname(CLIENT)
sys.path.insert(0, HERE)
sys.path.insert(0, CLIENT)

from executor import run  # noqa: E402
from generate import generate  # noqa: E402
from normalize import ScenarioError, normalize  # noqa: E402
from stackchan import StackChan  # noqa: E402
from toio_client import Toio  # noqa: E402


def format_summary(scenario):
    lines = [f"タイトル: {scenario['title']}"]
    for index, step in enumerate(scenario["steps"], start=1):
        said = step["say"] or "（なし）"
        lines.append(
            f"{index}. 「{said}」 顔={step['face']} 視線={step['look']} 体={step['body']} "
            f"toio={step['toio_move']} 対象={step['toio_group']} 色={step['toio_color']} "
            f"音={step['toio_sound']} 間={step['pause']}秒"
        )
    return "\n".join(lines)


def save_scenario(scenario, root=ROOT):
    folder = os.path.join(root, "scenarios")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(scenario, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def load_scenario(path):
    with open(path, encoding="utf-8") as handle:
        return normalize(json.load(handle))


def _hubs(args):
    stackchan = None if args.no_stackchan else StackChan(args.stackchan_hub, timeout=45, raise_errors=False)
    toio = None if args.no_toio else Toio(args.toio_hub, timeout=20, raise_errors=False)
    return stackchan, toio


def _execute(scenario, args):
    if args.generate_only:
        return
    stackchan, toio = _hubs(args)
    run(scenario, stackchan, toio, dry_run=args.dry_run)


def _generate_and_play(policy, args):
    raw = generate(policy, args.ai_url, args.model, args.steps, seed=args.seed, timeout=60)
    scenario = normalize(raw)
    print(format_summary(scenario))
    path = save_scenario(scenario)
    print(f"保存: {path}")
    _execute(scenario, args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("policy", nargs="?", help="この回の方針（日本語1行）")
    parser.add_argument("--generate-only", action="store_true", help="生成して保存するだけ")
    parser.add_argument("--from", dest="from_file", help="保存済みシナリオを再生（LLM を呼ばない）")
    parser.add_argument("--dry-run", action="store_true", help="送るコマンドを表示するだけ")
    parser.add_argument("--no-stackchan", action="store_true")
    parser.add_argument("--no-toio", action="store_true")
    parser.add_argument("--interactive", action="store_true", help="方針を繰り返し読む。空行で終了")
    parser.add_argument("--ai-url", default=os.environ.get("AI_URL") or "http://192.168.100.143:8080/v1/chat/completions")
    parser.add_argument("--model", default=os.environ.get("AI_MODEL") or "qwen2.5-3b")
    parser.add_argument("--steps", type=int, default=6, help="最大ステップ数（3〜8、既定 6）")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--stackchan-hub", default=os.environ.get("STACKCHAN_HUB") or "http://127.0.0.1:8766")
    parser.add_argument("--toio-hub", default=os.environ.get("TOIO_HUB") or "http://127.0.0.1:8765")
    args = parser.parse_args(argv)

    try:
        if args.interactive:
            while True:
                try:
                    policy = input("方針> ").strip()
                except EOFError:
                    print()
                    return 0
                if not policy:
                    return 0
                _generate_and_play(policy, args)
            return 0
        if args.from_file:
            scenario = load_scenario(args.from_file)
            print(format_summary(scenario))
            _execute(scenario, args)
            return 0
        if not args.policy:
            parser.error("方針テキストか --from か --interactive が必要です")
        _generate_and_play(args.policy, args)
        return 0
    except (ScenarioError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
