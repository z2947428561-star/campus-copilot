"""Check captured real-account guide answers for correctness and requested scope."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'data/local/xmumdorm/imported-guide-questions.json'


def focused(name, answer):
    if name == 'campus_accounts':
        return len(answer) <= 60 and not re.search('密码|同步|重置|护照', answer)
    if name == 'campus_gym':
        return len(answer) <= 180 and not re.search(r'图书馆|食堂|超市|游泳池|球场', answer)
    if name == 'food_apps':
        return len(answer) <= 60 and not re.search('优惠|建议|地址|配送费', answer)
    return len(answer) <= 120


def main():
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    for item in report['cases']:
        item['focused'] = focused(item['name'], item['answer'])
        item['clean_output'] = not re.search(r'来源[:：]|生效日期|collected_at|effective_date|^我先|^我查|^来自', item['answer'])
    report['passed'] = all(item['passed'] and item['focused'] and item['clean_output'] for item in report['cases'])
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'cases': [{key: item[key] for key in ('name', 'passed', 'focused', 'clean_output')} for item in report['cases']]}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
