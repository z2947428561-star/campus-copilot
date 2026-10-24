"""Verify the real model against the actual shared Holidays module, with fixture identity."""
import os
from verify_dorm_personal import ROOT, main


def checks(name, answer, payloads):
    data = [item.get('data', {}) for item in payloads if item.get('status') == 'ok']
    if not data: return {'module_data_correct': False}
    result = data[-1]
    items = result.get('items', [])
    if name == 'next_holiday':
        correct = len(items) == 1 and items[0]['id'] == 'deepavali-2026' and items[0]['daysUntil'] == 15
    elif name == 'semester_holidays':
        correct = [item['id'] for item in items] == ['deepavali-2026', 'selangor-sultan-2026', 'christmas-2026', 'new-year-2027']
    elif name == 'named_holiday':
        correct = len(items) == 1 and items[0]['start'] == '2027-12-25'
    elif name == 'unrecorded_year':
        correct = result.get('status') == 'not_recorded' and not items and not any(word in answer for word in ['春节', '圣诞', '屠妖'])
    else:
        correct = result.get('status') == 'no_record' and not items
    return {'module_data_correct': correct, 'no_source_preamble': not answer.startswith(('来自', '根据网站'))}


if __name__ == '__main__':
    os.environ['CAMPUS_TEST_NOW'] = '2026-10-24T03:30:00Z'
    raise SystemExit(main(profile=ROOT / 'data/local/xmumdorm/holiday-verification', case_check=checks, cases=[
        ('next_holiday', '7', '下次放假是什么时候？还有几天？', 'get_campus_holidays', ['屠妖节', '15']),
        ('semester_holidays', '7', '这学期有什么节日？', 'get_campus_holidays', ['屠妖节', '雪兰莪苏丹生日', '圣诞节', '元旦']),
        ('named_holiday', '7', '2027年圣诞节是哪天？', 'get_campus_holidays', ['2027', '圣诞', '25']),
        ('unrecorded_year', '7', '2030年有哪些公共假期？', 'get_campus_holidays', []),
        ('tomorrow', '7', '明天有假期吗？', 'get_campus_holidays', []),
    ]))
