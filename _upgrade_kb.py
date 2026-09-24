# -*- coding: utf-8 -*-
"""给作品版 kb.json 的规则加 _category 标注 + 优化 ship_time 匹配（仅作品副本，不影响原项目）"""
import json

P = r'd:\traework\6aae8dd9cbf1d382b9c007d0\ai-cs-agent\backend\data\kb.json'
kb = json.load(open(P, encoding='utf-8'))

CAT = {
    'style_guide': '脚踏与挡杆',
    'pedal_A_chosen': '脚踏与挡杆',
    'pedal_B_chosen': '脚踏与挡杆',
    'greet_first': None,          # 通用
    'pedal_B': '脚踏与挡杆',
    'pedal_A': '脚踏与挡杆',
    'pedal_install': '脚踏与挡杆',
    'pedal_A_real': '脚踏与挡杆',
    'pedal_A_package': '脚踏与挡杆',
    'pedal_A_features': '脚踏与挡杆',
    'shifter_fit': '脚踏与挡杆',
    'shorttail_fit': '短尾',
    'shorttail_adjust': '短尾',
    'wingcover_fit': '定风翼堵盖',
    'wingcover_install': '定风翼堵盖',
    'ship_time': None,            # 通用
    'ship_fee': None,
    'return_policy': None,
    'price_ask': None,
    'price_bargain': None,
    'ship_from': None,
    'install_go_shop': '脚踏与挡杆',
    'install_leave_msg': '脚踏与挡杆',
    'install_ask': '脚踏与挡杆',
}

for r in kb['rules']:
    r['_category'] = CAT.get(r['id'])

# ship_time 去掉裸「发货」，避免与 ship_from 抢「在哪里发货」
for r in kb['rules']:
    if r['id'] == 'ship_time':
        r['match'] = [w for w in r['match'] if w != '发货']
        r['_说明'] = '（作品版优化）去掉裸「发货」，避免与 ship_from 抢命中「在哪里发货」'

json.dump(kb, open(P, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('完成：_category 标注 + ship_time 优化')
for r in kb['rules']:
    print(' ', r['id'], '->', r.get('_category'))
