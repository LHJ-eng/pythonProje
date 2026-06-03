# ============================================================
# 问题1：基本情形下的单精灵捕捉策略
# 运行方式：python question1.py
# ============================================================

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ======================== 全局数据 ========================

BALLS_DATA = {
    '高级球':   {'cost': 12000,   'base_rate': 0.40, 'fixed_talent': None, 'fixed_color': None},
    '属性球':   {'cost': 3000,    'base_rate': 0.30, 'fixed_talent': None, 'fixed_color': None},
    '补光球':   {'cost': 80000,   'base_rate': 1.00, 'fixed_talent': None, 'fixed_color': None},
    '国王球':   {'cost': 160000,  'base_rate': 1.00, 'fixed_talent': 5,    'fixed_color': None},
    '棱镜球':   {'cost': 3200000, 'base_rate': 1.00, 'fixed_talent': None, 'fixed_color': 10},
}

P_MATCH = 0.5  # 属性球匹配概率
DOUBLE_REVENUE = 2.0  # 牵手双倍收益

TALENT_DATA = [
    ('了不起', 5, 0.02),
    ('相当好', 3, 0.08),
    ('还不错', 2, 0.30),
    ('一般般', 1, 0.60),
]

COLOR_DATA = [
    ('异色',      10,   0.018),
    ('炫彩',      10,   0.018),
    ('异色+炫彩', 100,  0.000324),
    ('噩梦污染',   5,   0.05),
    ('普通外观',   1,   0.913676),
]

MEDAL_DATA = [
    ('完美无瑕', 3, 5), ('粗嗓门', 3, 5), ('婉转声', 3, 5),
    ('小不点', 3, 5), ('大块头', 3, 5),
    ('王国颂歌', 2, 10), ('青风之息', 2, 10),
    ('晨光破晓', 2, 3.75), ('灼日凌空', 2, 3.75),
    ('暮色衔山', 2, 3.75), ('星月交汇', 2, 3.75),
]

POKEMON_DATA = [
    ('恶魔狼',   '恶魔狼',        6000, 0.75),
    ('月牙雪熊', '月牙雪熊',      4500, 0.85),
    ('犀角鸟',   '犀角鸟',        2400, 0.90),
    ('绒绒',     '绒绒',          2400, 0.90),
    ('粉星仔',   '粉星仔',        2400, 0.90),
    ('治愈兔',   '治愈兔(低阶)',  1800, 0.95),
    ('治愈兔',   '治愈兔(中阶)',  3150, 0.90),
    ('治愈兔',   '治愈兔(高阶)',  4500, 0.85),
    ('奇丽草',   '奇丽草(低阶)',  1800, 0.95),
    ('奇丽草',   '奇丽草(中阶)',  3150, 0.90),
    ('奇丽草',   '奇丽草(高阶)',  4500, 0.85),
    ('大耳帽兜', '大耳帽兜(低阶)',1800, 0.95),
    ('大耳帽兜', '大耳帽兜(中阶)',3150, 0.90),
    ('大耳帽兜', '大耳帽兜(高阶)',4500, 0.85),
    ('拉特',     '拉特(低阶)',    1800, 0.95),
    ('拉特',     '拉特(高阶)',    4500, 0.85),
    ('呼呼猪',   '呼呼猪(低阶)',  1800, 0.95),
    ('呼呼猪',   '呼呼猪(高阶)',  4500, 0.85),
    ('格兰种子', '格兰种子(低阶)',1200, 1.00),
    ('格兰种子', '格兰种子(中阶)',2100, 0.95),
    ('格兰种子', '格兰种子(高阶)',3000, 0.90),
]

FAMILY_MAP = defaultdict(list)
for fam, form, price, rate in POKEMON_DATA:
    FAMILY_MAP[fam].append({'form': form, 'base_price': price, 'capture_rate': rate})

# ======================== 问题1主程序 ========================

print("=" * 60)
print("问题1：基本情形下的单精灵捕捉策略（恶魔狼）")
print("=" * 60)

DEMON_WOLF_BASE_PRICE = 6000
DEMON_WOLF_CAPTURE_RATE = 0.75

# 计算各球种期望净收益
ball_names = list(BALLS_DATA.keys())
results_p1 = []

for name in ball_names:
    ball = BALLS_DATA[name]
    cost = ball['cost']
    base_rate = ball['base_rate']
    actual_rate = base_rate * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        actual_rate *= P_MATCH
    expected_revenue = actual_rate * DEMON_WOLF_BASE_PRICE * DOUBLE_REVENUE
    expected_net = expected_revenue - cost
    results_p1.append({
        '球种': name,
        '成本': cost,
        '实际成功率': f"{actual_rate:.2%}",
        '期望收益': round(expected_revenue, 2),
        '期望净收益': round(expected_net, 2),
    })

df_p1 = pd.DataFrame(results_p1)
print("\n各球种期望净收益表：")
print(df_p1.to_string(index=False))

optimal_ball_p1 = df_p1.loc[df_p1['期望净收益'].idxmax(), '球种']
optimal_net_p1 = df_p1['期望净收益'].max()
print(f"\n最优球种: {optimal_ball_p1}")
print(f"最优期望净收益（每次尝试）: {optimal_net_p1:.2f} 洛克贝")

# 连续捕捉N只分析
print("\n--- 连续捕捉N只分析 ---")
print("每次尝试独立 → 最优球种不随N变化（各球种排序固定）")
print("\n若理解为'成功捕获N只'：")
for name in ball_names[:4]:
    ball = BALLS_DATA[name]
    actual_rate = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if actual_rate > 0:
        e_cost_per_capture = ball['cost'] / actual_rate
        e_net_per_capture = DEMON_WOLF_BASE_PRICE - e_cost_per_capture
        print(f"  {name}: 平均{cost/actual_rate:,.0f}洛克贝/只, 净收益{e_net_per_capture:,.0f}/只")
print("结论：高级球始终最优，因性价比（收益/成本比）排名固定")

# ======================== 图表 ========================

bars_net = df_p1['期望净收益'].values
ball_names_arr = df_p1['球种'].values

# 图1：各球种期望净收益柱状图
fig1, ax1 = plt.subplots(figsize=(12, 7))
colors_bar = ['#3B7DD8' if n == optimal_ball_p1 else '#A0C4E8' for n in ball_names_arr]
edge_colors_bar = ['#1A5276' if n == optimal_ball_p1 else '#7FA8C9' for n in ball_names_arr]
lw_bar = [2.5 if n == optimal_ball_p1 else 1.0 for n in ball_names_arr]

bars = ax1.bar(ball_names_arr, bars_net, color=colors_bar, edgecolor=edge_colors_bar, linewidth=lw_bar)

# 自动标注：正值标在柱顶上方，负值标在柱底下方
y_range = bars_net.max() - bars_net.min()
for bar, val in zip(bars, bars_net):
    if val >= 0:
        text_y = bar.get_height() + y_range * 0.03
        va_align = 'bottom'
    else:
        text_y = bar.get_height() - y_range * 0.03
        va_align = 'top'
    ax1.text(bar.get_x() + bar.get_width()/2, text_y, f'{val:,.0f}',
             ha='center', va=va_align, fontsize=10.5, fontweight='bold')

ax1.axhline(y=0, color='#333333', linewidth=1.0, linestyle='-')
ax1.set_title('问题1：各球种期望净收益对比\n（恶魔狼·基础售价6,000·无随机倍率）',
              fontsize=15, fontweight='bold', pad=16)
ax1.set_ylabel('期望净收益（洛克贝）', fontsize=13, labelpad=8)
ax1.set_xlabel('球种', fontsize=13, labelpad=8)
ax1.grid(axis='y', alpha=0.25, linestyle='--', linewidth=0.7)
ax1.tick_params(axis='x', labelsize=11)
ax1.tick_params(axis='y', labelsize=10)
ax1.set_ylim(bars_net.min() * 1.15, bars_net.max() * 1.15 if bars_net.max() > 0 else bars_net.max() * 0.85)
plt.tight_layout(pad=2.0)
plt.savefig('p1_fig1_净收益柱状图.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("\n图1已保存: p1_fig1_净收益柱状图.png")

# 图2：不同N下连续使用最优球种的总期望收益折线图
N_range = np.arange(1, 101)
fig2, ax2 = plt.subplots(figsize=(11, 7))
color_cycle = ['#3B7DD8', '#E8913A', '#4CAF50', '#F44336', '#9C27B0']

for idx, name in enumerate(ball_names_arr):
    ball = BALLS_DATA[name]
    actual_rate = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        actual_rate *= P_MATCH
    e_net_per_try = actual_rate * DEMON_WOLF_BASE_PRICE - ball['cost']
    cumulative = N_range * e_net_per_try
    ls = '-' if name == optimal_ball_p1 else (0, (4, 2))
    lw = 2.8 if name == optimal_ball_p1 else 1.5
    alpha_val = 1.0 if name == optimal_ball_p1 else 0.65
    z_val = 5 if name == optimal_ball_p1 else 2
    ax2.plot(N_range, cumulative, label=name, linewidth=lw, linestyle=ls,
             color=color_cycle[idx % len(color_cycle)], alpha=alpha_val, zorder=z_val)

ax2.set_title('问题1：连续N次尝试的总期望净收益', fontsize=15, fontweight='bold', pad=16)
ax2.set_xlabel('尝试次数 N', fontsize=13, labelpad=8)
ax2.set_ylabel('总期望净收益（洛克贝）', fontsize=13, labelpad=8)
ax2.legend(fontsize=10.5, loc='best', framealpha=0.92, fancybox=True, shadow=False,
           edgecolor='#CCCCCC')
ax2.grid(alpha=0.25, linestyle='--', linewidth=0.7)
ax2.tick_params(labelsize=10)
plt.tight_layout(pad=2.0)
plt.savefig('p1_fig2_累积收益.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图2已保存: p1_fig2_累积收益.png")

# 图3：成本与成功率的双轴图
fig3, ax3_left = plt.subplots(figsize=(12, 7))
x_pos = np.arange(len(ball_names_arr))
width = 0.38

rates = []
costs = []
for n in ball_names_arr:
    ball = BALLS_DATA[n]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if n == '属性球':
        r *= P_MATCH
    rates.append(r * 100)
    costs.append(ball['cost'])

bars_cost = ax3_left.bar(x_pos - width/2, costs, width, label='成本（洛克贝）',
                          color='#3B7DD8', edgecolor='white', linewidth=1.2, alpha=0.85)
ax3_left.set_ylabel('成本（洛克贝）', fontsize=13, color='#3B7DD8', labelpad=8)
ax3_left.tick_params(axis='y', labelcolor='#3B7DD8', labelsize=10)

for bar, c in zip(bars_cost, costs):
    ax3_left.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(costs)*0.015,
                  f'{c:,}', ha='center', va='bottom', fontsize=8.5, color='#3B7DD8', fontweight='bold')

ax3_right = ax3_left.twinx()
line_rate = ax3_right.plot(x_pos + width/2, rates, 'D-', color='#E8313A', linewidth=2.5,
               markersize=9, markerfacecolor='white', markeredgewidth=2,
               label='实际成功率(%)', zorder=10)

for i, r in enumerate(rates):
    offset_y = max(rates) * 0.04
    ax3_right.annotate(f'{r:.1f}%', (x_pos[i] + width/2, r + offset_y),
                       ha='center', fontsize=8.5, color='#E8313A', fontweight='bold')

ax3_right.set_ylabel('实际成功率 (%)', fontsize=13, color='#E8313A', labelpad=8)
ax3_right.tick_params(axis='y', labelcolor='#E8313A', labelsize=10)
ax3_right.set_ylim(0, max(rates) * 1.18)

ax3_left.set_xticks(x_pos)
ax3_left.set_xticklabels(ball_names_arr, fontsize=11)
ax3_left.set_title('问题1：各球种成本与实际成功率双轴图', fontsize=15, fontweight='bold', pad=16)
lines1, labels1 = ax3_left.get_legend_handles_labels()
lines2, labels2 = ax3_right.get_legend_handles_labels()
ax3_left.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=10.5,
                framealpha=0.92, edgecolor='#CCCCCC')
ax3_left.grid(alpha=0.2, axis='y', linestyle='--', linewidth=0.7)
plt.tight_layout(pad=2.0)
plt.savefig('p1_fig3_双轴图.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图3已保存: p1_fig3_双轴图.png")

# 图4：左-净收益热图；右-成本敏感性Tornado图
fig4, (ax4a, ax4b) = plt.subplots(1, 2, figsize=(18, 8))

# 左子图：热图
cost_range = np.linspace(0, 3500000, 400)
rate_range = np.linspace(0, 1.0, 200)
C_grid, R_grid = np.meshgrid(cost_range, rate_range)
net_grid = R_grid * DEMON_WOLF_BASE_PRICE - C_grid

im4a = ax4a.imshow(net_grid, extent=[0, 3500000, 0, 1.0], origin='lower',
                   aspect='auto', cmap='RdYlGn', vmin=-3500000, vmax=10000, alpha=0.85)

# 球种标注——自动计算偏移，避免重叠
ball_pts = []
for name in ball_names_arr:
    ball = BALLS_DATA[name]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        r *= P_MATCH
    ball_pts.append((name, ball['cost'], r))
ball_pts.sort(key=lambda x: x[1])  # 按成本排序

# 根据成本间距动态设置偏移
prev_c = -1
for i, (name, c, r) in enumerate(ball_pts):
    is_opt = (name == optimal_ball_p1)
    marker = 'D' if is_opt else 'o'
    size = 180 if is_opt else 90
    ec = '#1A5276' if is_opt else '#555555'
    fc = '#FFD700' if is_opt else '#3B7DD8'
    lw = 2.5 if is_opt else 1.5

    ax4a.scatter(c, r, s=size, c=fc, marker=marker, edgecolors=ec,
                linewidths=lw, zorder=10, alpha=0.92)

    # 自动偏移：交替上下放置
    if i % 2 == 0:
        xytext = (25, 18)
    else:
        xytext = (25, -18)
    # 最优球额外偏移避免被遮挡
    if is_opt:
        xytext = (-35, 22)

    ax4a.annotate(name, (c, r), textcoords="offset points",
                 xytext=xytext, fontsize=9.5, fontweight='bold', zorder=12,
                 bbox=dict(boxstyle='round,pad=0.25', facecolor='white',
                          alpha=0.92, edgecolor='#CCCCCC', linewidth=0.8),
                 arrowprops=dict(arrowstyle='->', color='#555555', lw=1.2))

ax4a.set_xlabel('球成本（洛克贝）', fontsize=13, labelpad=8)
ax4a.set_ylabel('实际成功率', fontsize=13, labelpad=8)
ax4a.set_title('净收益热图与球种定位', fontsize=14, fontweight='bold', pad=12)
cbar4a = plt.colorbar(im4a, ax=ax4a, shrink=0.88, pad=0.02)
cbar4a.set_label('期望净收益（洛克贝）', fontsize=11, labelpad=8)
ax4a.grid(alpha=0.15, linestyle='--', linewidth=0.5)
ax4a.tick_params(labelsize=10)

# 右子图：Tornado图
sensitivity_data = []
for name in ball_names_arr:
    ball = BALLS_DATA[name]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        r *= P_MATCH
    base_net = r * DEMON_WOLF_BASE_PRICE - ball['cost']
    net_low = r * DEMON_WOLF_BASE_PRICE - ball['cost'] * 1.2
    net_high = r * DEMON_WOLF_BASE_PRICE - ball['cost'] * 0.8
    sensitivity_data.append({
        '球种': name, '基准': base_net,
        '成本+20%': net_low, '成本-20%': net_high,
        '敏感度': (net_high - net_low) / 2,
    })

df_sens = pd.DataFrame(sensitivity_data).sort_values('敏感度', ascending=True)
y_pos = np.arange(len(df_sens))

ax4b.barh(y_pos, df_sens['成本+20%'] - df_sens['基准'],
          left=df_sens['基准'] - df_sens['敏感度'],
          color='#E8313A', edgecolor='white', height=0.55, alpha=0.75, label='成本+20%', zorder=3)
ax4b.barh(y_pos, df_sens['成本-20%'] - df_sens['基准'],
          left=df_sens['基准'],
          color='#3B7DD8', edgecolor='white', height=0.55, alpha=0.75, label='成本-20%', zorder=3)

for i, row in df_sens.iterrows():
    idx = list(df_sens['球种']).index(row['球种'])
    x_range = df_sens['基准'].max() - df_sens['基准'].min()
    offset = x_range * 0.015
    ax4b.annotate(f"{row['基准']:+,.0f}", (row['基准'], idx),
                 ha='center', va='bottom', fontsize=9, fontweight='bold', color='#333333',
                 xytext=(0, 3), textcoords='offset points')

ax4b.set_yticks(y_pos)
ax4b.set_yticklabels(df_sens['球种'], fontsize=11)
ax4b.set_xlabel('期望净收益（洛克贝）', fontsize=13, labelpad=8)
ax4b.set_title('成本敏感性分析（±20%波动）', fontsize=14, fontweight='bold', pad=12)
ax4b.legend(fontsize=10.5, loc='lower right', framealpha=0.92, edgecolor='#CCCCCC')
ax4b.grid(axis='x', alpha=0.2, linestyle='--', linewidth=0.7)
ax4b.axvline(x=0, color='#333333', linewidth=1.5)
ax4b.tick_params(labelsize=10)

fig4.suptitle('问题1：期望净收益敏感性分析', fontsize=16, fontweight='bold', y=1.01)
plt.tight_layout(pad=3.0)
plt.savefig('p1_fig4_敏感性分析.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图4已保存: p1_fig4_敏感性分析.png")

# ======================== 深度优化图表 ========================

# 图5：效率前沿——更好的等值线和自动标注
fig5, ax5 = plt.subplots(figsize=(15, 10))
cost_grid = np.logspace(np.log10(100), np.log10(4500000), 300)
rate_grid = np.linspace(0.01, 1.0, 250)
C_mesh, R_mesh = np.meshgrid(cost_grid, rate_grid)
net_mesh = R_mesh * DEMON_WOLF_BASE_PRICE - C_mesh

# 更合理的等值线级别
all_nets = [R_mesh[j,i] * DEMON_WOLF_BASE_PRICE - C_mesh[j,i]
            for j in range(len(rate_grid)) for i in range(len(cost_grid))]
net_min = np.min(all_nets)
net_max = np.max(all_nets)
contour_levels = np.linspace(net_min, net_max, 12)

CS = ax5.contour(C_mesh, R_mesh, net_mesh, levels=contour_levels,
                 colors='#666666', linewidths=0.9, linestyles='--', alpha=0.5)
ax5.clabel(CS, inline=True, fontsize=7.5, fmt='%.0f', inline_spacing=8)

cf = ax5.contourf(C_mesh, R_mesh, net_mesh, levels=60, cmap='RdYlGn', alpha=0.35)

# 球种定位——动态偏移
ball_list = []
for name in ball_names_arr:
    ball = BALLS_DATA[name]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        r *= P_MATCH
    c = ball['cost']
    net_each = r * DEMON_WOLF_BASE_PRICE - c
    ball_list.append((name, c, r, net_each))
ball_list.sort(key=lambda x: x[3], reverse=True)

# 智能偏移：根据log空间中的相邻间距计算
dx_log = 0.12
dy = 0.055
seen_positions = []
for i, (name, c, r, net_each) in enumerate(ball_list):
    is_opt = (name == optimal_ball_p1)
    fc = '#FFD700' if is_opt else '#3B7DD8'
    size = 240 if is_opt else 130
    marker = 'D' if is_opt else 'o'
    ec = '#1A5276' if is_opt else '#444444'
    ew = 2.5 if is_opt else 1.5

    ax5.scatter(c, r, s=size, c=fc, marker=marker, edgecolors=ec,
               linewidths=ew, zorder=15, alpha=0.92)

    # 四象限偏移，避免重叠
    offsets_list = [(-80, 30), (70, 35), (-90, -28), (75, -30), (0, 45)]
    ox, oy = offsets_list[i % len(offsets_list)]
    if is_opt:
        ox, oy = (-85, -32)

    ax5.annotate(f'{name}\n(净{net_each:+,.0f})', (c, r),
                 textcoords="offset points", xytext=(ox, oy),
                 fontsize=9, ha='center', fontweight='bold', zorder=16,
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                          alpha=0.93, edgecolor='#AAAAAA', linewidth=0.8),
                 arrowprops=dict(arrowstyle='->', color='#666666', lw=1.0, alpha=0.7))

ax5.set_xscale('log')
cbar5 = plt.colorbar(cf, ax=ax5, label='期望净收益（洛克贝）', shrink=0.82, pad=0.02)
cbar5.ax.tick_params(labelsize=9)
ax5.set_xlabel('球成本（洛克贝·对数尺度）', fontsize=14, fontweight='bold', labelpad=10)
ax5.set_ylabel('实际成功率', fontsize=14, fontweight='bold', labelpad=10)
ax5.set_title('问题1：捕捉效率前沿与盈亏平衡分析', fontsize=16, fontweight='bold', pad=18)
ax5.grid(alpha=0.18, linestyle='--', linewidth=0.5)
ax5.set_xlim(100, 4500000)
ax5.tick_params(labelsize=10)

from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker='D', color='w', markerfacecolor='#FFD700',
           markersize=13, markeredgecolor='#1A5276', markeredgewidth=2.5, label='最优球种'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='#3B7DD8',
           markersize=11, markeredgecolor='#444444', markeredgewidth=1.5, label='其他球种'),
    Line2D([0], [0], color='#666666', linestyle='--', linewidth=1.2, alpha=0.6, label='等净收益线'),
]
ax5.legend(handles=legend_elements, loc='upper right', fontsize=10.5,
          framealpha=0.93, fancybox=True, edgecolor='#CCCCCC')

plt.tight_layout(pad=3.0)
plt.savefig('p1_fig5_效率前沿.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图5已保存: p1_fig5_效率前沿.png")

# 图6：ROI排名+收益分解
fig6, (ax6a, ax6b) = plt.subplots(1, 2, figsize=(17, 8))

roi_vals = []
for name in ball_names_arr:
    ball = BALLS_DATA[name]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if name == '属性球':
        r *= P_MATCH
    e_rev = r * DEMON_WOLF_BASE_PRICE
    roi_vals.append(((e_rev - ball['cost']) / ball['cost'] * 100, name))

roi_sorted = sorted(roi_vals, key=lambda x: x[0], reverse=True)
names_r = [x[1] for x in roi_sorted]
vals_r = [x[0] for x in roi_sorted]
roi_colors = ['#2E7D32' if v >= 0 else '#D32F2F' for v in vals_r]

bars6a = ax6a.barh(names_r, vals_r, color=roi_colors, edgecolor='white', height=0.62, linewidth=1.2)
for bar, val in zip(bars6a, vals_r):
    gap = max(abs(v) for v in vals_r) * 0.03
    x_pos_val = bar.get_width() + gap if val >= 0 else bar.get_width() - gap
    ha_val = 'left' if val >= 0 else 'right'
    ax6a.text(x_pos_val, bar.get_y() + bar.get_height()/2,
              f'{val:+.1f}%', va='center', fontsize=11, fontweight='bold', ha=ha_val,
              color='#2E7D32' if val >= 0 else '#D32F2F')

ax6a.axvline(x=0, color='#333333', linewidth=1.2, linestyle='-')
ax6a.set_title('ROI 排名（净收益 ÷ 成本）', fontsize=15, fontweight='bold', pad=14)
ax6a.set_xlabel('ROI (%)', fontsize=13, labelpad=8)
ax6a.grid(axis='x', alpha=0.2, linestyle='--', linewidth=0.7)
ax6a.tick_params(axis='y', labelsize=11)

x6 = np.arange(len(ball_names_arr))
w6 = 0.35
revs = []
costs6 = []
for n in ball_names_arr:
    ball = BALLS_DATA[n]
    r = ball['base_rate'] * DEMON_WOLF_CAPTURE_RATE
    if n == '属性球':
        r *= P_MATCH
    revs.append(r * DEMON_WOLF_BASE_PRICE)
    costs6.append(ball['cost'])

bars_rev = ax6b.bar(x6 - w6/2, revs, w6, label='期望收益', color='#3B7DD8',
                    edgecolor='white', linewidth=1.2, alpha=0.88)
bars_cost = ax6b.bar(x6 + w6/2, costs6, w6, label='成本', color='#E8313A',
                     edgecolor='white', linewidth=1.2, alpha=0.88)

y_all = revs + costs6
y_range6 = max(y_all) - min(y_all)
for i, (r_val, c_val) in enumerate(zip(revs, costs6)):
    net = r_val - c_val
    text_y = max(r_val, c_val) + y_range6 * 0.04
    ax6b.annotate(f'净{net:+,.0f}', (i, text_y), ha='center', fontsize=9.5,
                 fontweight='bold', color='#333333',
                 bbox=dict(boxstyle='round,pad=0.2', facecolor='#FFFDE7', alpha=0.85,
                          edgecolor='#DDDDDD', linewidth=0.6))

ax6b.set_xticks(x6)
ax6b.set_xticklabels(ball_names_arr, fontsize=10.5, rotation=12, ha='right')
ax6b.set_title('单位成本收益分解', fontsize=15, fontweight='bold', pad=14)
ax6b.legend(fontsize=11, loc='upper right', framealpha=0.92, edgecolor='#CCCCCC')
ax6b.grid(axis='y', alpha=0.2, linestyle='--', linewidth=0.7)
ax6b.ticklabel_format(style='plain', axis='y')
ax6b.tick_params(labelsize=10)

fig6.suptitle('问题1：深度效率分析', fontsize=17, fontweight='bold', y=1.02)
plt.tight_layout(pad=3.0)
plt.savefig('p1_fig6_ROI分析.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图6已保存: p1_fig6_ROI分析.png")

# ======================== CSV 数据导出 ========================

df_p1.to_csv('p1_球种期望净收益.csv', index=False, encoding='utf-8-sig')
print("\nCSV已导出: p1_球种期望净收益.csv")
print("\n问题1 完成！")
