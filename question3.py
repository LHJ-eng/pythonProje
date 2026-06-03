# ============================================================
# 问题3：嵌入噩梦枷锁保底机制后的家族专精策略
# 运行方式：python question3.py
# ============================================================

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
import seaborn as sns
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

P_MATCH = 0.5

TALENT_DATA = [
    ('了不起', 5, 0.02), ('相当好', 3, 0.08),
    ('还不错', 2, 0.30), ('一般般', 1, 0.60),
]

COLOR_DATA = [
    ('异色', 10, 0.018), ('炫彩', 10, 0.018),
    ('异色+炫彩', 100, 0.000324), ('噩梦污染', 5, 0.05),
    ('普通外观', 1, 0.913676),
]

MEDAL_DATA = [
    ('完美无瑕', 3, 5), ('粗嗓门', 3, 5), ('婉转声', 3, 5),
    ('小不点', 3, 5), ('大块头', 3, 5),
    ('王国颂歌', 2, 10), ('青风之息', 2, 10),
    ('晨光破晓', 2, 3.75), ('灼日凌空', 2, 3.75),
    ('暮色衔山', 2, 3.75), ('星月交汇', 2, 3.75),
]

POLLUTION_TRIGGER = 20
PITY_COUNTER_MAX = 80
SHINY_DROP_RATE = 0.018
SHINY_PITY_RATE = 1.0 / PITY_COUNTER_MAX
DOUBLE_REVENUE = 2.0

# ======================== 通用函数 ========================

def sample_talent():
    r = np.random.random()
    cum = 0
    for _, mult, prob in TALENT_DATA:
        cum += prob
        if r < cum: return mult
    return 1.0

def sample_color():
    r = np.random.random()
    cum = 0
    for _, mult, prob in COLOR_DATA:
        cum += prob
        if r < cum: return mult
    return 1.0

def sample_medal():
    medal_mults = {m[0]: m[1] for m in MEDAL_DATA}
    medal_weights = [m[2] for m in MEDAL_DATA]
    total_weight = sum(medal_weights)
    medal_probs = [w / total_weight for w in medal_weights]
    medal_names = [m[0] for m in MEDAL_DATA]
    acquired = set()
    product_mult = 1.0
    for _ in range(5):
        if np.random.random() < 0.40:
            available = [(n, p) for n, p in zip(medal_names, medal_probs) if n not in acquired]
            if available:
                probs = np.array([a[1] for a in available])
                probs = probs / probs.sum()
                chosen = np.random.choice([a[0] for a in available], p=probs)
                acquired.add(chosen)
                product_mult *= medal_mults[chosen]
    return product_mult

def expected_medal_multiplier(n_sim=200000):
    total = 0.0
    for _ in range(n_sim):
        total += sample_medal()
    return total / n_sim

def sample_pokemon_price(base_price, fixed_talent=None, fixed_color=None):
    t = fixed_talent if fixed_talent is not None else sample_talent()
    c = fixed_color if fixed_color is not None else sample_color()
    m = sample_medal()
    return base_price * t * c * m

# ======================== 预计算 ========================

np.random.seed(42)
E_TALENT = sum(m*p for _, m, p in TALENT_DATA)
E_COLOR = sum(m*p for _, m, p in COLOR_DATA)
E_MEDAL = expected_medal_multiplier(200000)

S0 = 6000
r0 = 0.75

E_COLOR_SHINY = 10 * 0.982 + 100 * 0.018
E_PRICE_SHINY = S0 * E_TALENT * E_COLOR_SHINY * E_MEDAL

print("=" * 60)
print("问题3：嵌入噩梦枷锁保底机制后的家族专精策略")
print("=" * 60)
print(f"\n异色精灵期望售价 = {E_PRICE_SHINY:,.0f} 洛克贝")
print(f"  E[异色颜色] = 10×0.982 + 100×0.018 = {E_COLOR_SHINY:.2f}")

# ======================== 枚举(A,B)组合 ========================

ball_name_list = ['高级球', '属性球', '补光球', '国王球', '棱镜球']

def get_e_price_demon(ball_name):
    ball = BALLS_DATA[ball_name]
    if ball['fixed_talent'] is not None:
        return S0 * ball['fixed_talent'] * E_COLOR * E_MEDAL
    elif ball['fixed_color'] is not None:
        return S0 * E_TALENT * ball['fixed_color'] * E_MEDAL
    return S0 * E_TALENT * E_COLOR * E_MEDAL

combo_results = []
for ball_A in ball_name_list:
    for ball_B in ball_name_list:
        ba = BALLS_DATA[ball_A]
        bb = BALLS_DATA[ball_B]
        p_capture = ba['base_rate'] * r0
        if ball_A == '属性球':
            p_capture *= P_MATCH

        E_price_A = get_e_price_demon(ball_A)
        E_normal = p_capture * E_price_A * DOUBLE_REVENUE
        E_pollution_tries = p_capture / POLLUTION_TRIGGER
        E_shiny_per_pollution = bb['base_rate'] * (SHINY_DROP_RATE + SHINY_PITY_RATE) * E_PRICE_SHINY * DOUBLE_REVENUE
        if ball_B == '属性球':
            E_shiny_per_pollution *= P_MATCH
        E_shiny = E_pollution_tries * E_shiny_per_pollution
        total_cost = ba['cost'] + E_pollution_tries * bb['cost']
        E_net = E_normal + E_shiny - total_cost

        combo_results.append({
            '普通球种A': ball_A, '污染球种B': ball_B,
            '期望净收益': round(E_net, 2),
        })

df_combo = pd.DataFrame(combo_results)
best = df_combo.loc[df_combo['期望净收益'].idxmax()]
best_A = best['普通球种A']
best_B = best['污染球种B']
best_net = best['期望净收益']

print(f"\n最优组合: A={best_A}, B={best_B}")
print(f"期望净收益: {best_net:,.0f} 洛克贝/次")

# 对比分析
E_price_king = S0 * 5.0 * E_COLOR * E_MEDAL
no_pity_net = 1.0 * r0 * E_price_king * DOUBLE_REVENUE - BALLS_DATA['国王球']['cost']

print(f"\n策略对比：")
print(f"  专精保底（{best_A}+{best_B}）: {best_net:,.0f} 洛克贝/次")
print(f"  无视保底（国王球随意）:       {no_pity_net:,.0f} 洛克贝/次")
print(f"  专精优势: {best_net - no_pity_net:,.0f} ({(best_net/no_pity_net-1)*100:+.1f}%)")

# ======================== 蒙特卡洛仿真 ========================

def simulate_family(n_captures_target=2000):
    ba = BALLS_DATA[best_A]
    bb = BALLS_DATA[best_B]

    total_cost = 0
    total_revenue = 0
    captures = 0
    pity_counter = 0
    attempts = 0
    avg_net_history = []

    while captures < n_captures_target:
        attempts += 1
        total_cost += ba['cost']

        if np.random.random() < ba['base_rate'] * r0:
            captures += 1
            price = sample_pokemon_price(S0, fixed_talent=ba['fixed_talent'],
                                         fixed_color=ba['fixed_color'])
            total_revenue += price * DOUBLE_REVENUE

            if captures % POLLUTION_TRIGGER == 0:
                total_cost += bb['cost']
                if np.random.random() < bb['base_rate']:
                    pity_counter += 1

                    if np.random.random() < SHINY_DROP_RATE:
                        shiny_c = 10 + (90 if np.random.random() < 0.018 else 0)
                        shiny_p = S0 * sample_talent() * shiny_c * sample_medal()
                        total_revenue += shiny_p * DOUBLE_REVENUE

                    if pity_counter >= PITY_COUNTER_MAX:
                        shiny_c = 10 + (90 if np.random.random() < 0.018 else 0)
                        shiny_p = S0 * sample_talent() * shiny_c * sample_medal()
                        total_revenue += shiny_p * DOUBLE_REVENUE
                        pity_counter = 0

        avg_net_history.append((total_revenue - total_cost) / attempts)

    return avg_net_history

print("\n运行蒙特卡洛仿真（目标2000次捕获）...")
avg_hist = simulate_family(2000)
print(f"仿真完成，最终平均净收益: {avg_hist[-1]:,.0f} 洛克贝/次")

# ======================== 图表 ========================

# 图1：热力图——优化字体大小和配色
pivot = df_combo.pivot_table(values='期望净收益', index='普通球种A', columns='污染球种B', aggfunc='first')
fig1, ax1 = plt.subplots(figsize=(11, 9))
sns.heatmap(pivot, annot=True, fmt=',.0f', cmap='RdYlGn', center=0,
            ax=ax1, cbar_kws={'label': '期望净收益（洛克贝/次）', 'shrink': 0.85},
            annot_kws={'fontsize': 10.5, 'fontweight': 'bold'},
            linewidths=1.2, linecolor='white')
ax1.set_title('问题3：不同(A,B)球种组合期望净收益热力图\n(颜色越绿越优·红色表示亏损)',
              fontsize=15, fontweight='bold', pad=16)
ax1.set_xlabel('污染战斗球种 B', fontsize=13, labelpad=8)
ax1.set_ylabel('普通捕捉球种 A', fontsize=13, labelpad=8)
ax1.tick_params(labelsize=11)
plt.tight_layout(pad=2.0)
plt.savefig('p3_fig1_热力图.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("\n图1已保存: p3_fig1_热力图.png")

# 图2：流程图——保持原代码结构但微调间距
fig2, ax2 = plt.subplots(figsize=(24, 15))
ax2.set_xlim(0, 24)
ax2.set_ylim(0, 14)
ax2.axis('off')
ax2.set_title('问题3：噩梦枷锁保底机制完整流程图', fontsize=20, fontweight='bold', pad=30, y=0.98)

def draw_rect(ax, x, y, w, h, text, color, fontsize=12, edge_color='#333'):
    rect = plt.Rectangle((x - w/2, y - h/2), w, h, fill=True,
                         facecolor=color, edgecolor=edge_color, linewidth=2.2, alpha=0.92)
    ax.add_patch(rect)
    ax.text(x, y, text, ha='center', va='center', fontsize=fontsize,
            fontweight='bold', linespacing=1.3)

def draw_diamond(ax, x, y, w, h, text, color, fontsize=11):
    diamond = plt.Polygon([
        (x, y + h/2), (x + w/2, y), (x, y - h/2), (x - w/2, y)
    ], fill=True, facecolor=color, edgecolor='#333', linewidth=2.2, alpha=0.92)
    ax.add_patch(diamond)
    ax.text(x, y, text, ha='center', va='center', fontsize=fontsize, fontweight='bold')

def draw_sub(ax, x, y, w, h, text, color):
    rect = plt.Rectangle((x - w/2, y - h/2), w, h, fill=True,
                         facecolor=color, edgecolor='#999', linewidth=1.2, alpha=0.75)
    ax.add_patch(rect)
    ax.text(x, y, text, ha='center', va='center', fontsize=9, style='italic')

def arrow(ax, x1, y1, x2, y2, label='', style='solid', color=None):
    lw = 2.5 if style == 'solid' else 1.5
    ls = '-' if style == 'solid' else '--'
    c = color if color else ('#333' if style == 'solid' else '#888')
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', lw=lw, color=c,
                              linestyle=ls, mutation_scale=15, shrinkA=3, shrinkB=3))
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx + 0.2, my + 0.15, label, fontsize=11,
                fontweight='bold', color='#D32F2F', ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.1', facecolor='white', alpha=0.85))

L, M, R = 3.5, 12, 20.5
NW, NH = 4.2, 0.9
DW, DH = 3.8, 0.9
SW, SH = 4.2, 0.5

param_rect = plt.Rectangle((1.5, 12.6), 21, 0.8, fill=True,
                           facecolor='#F5F5F5', edgecolor='#AAAAAA', linewidth=1.5,
                           alpha=0.9, linestyle='--')
ax2.add_patch(param_rect)
ax2.text(12, 13.0, f'规则参数: 污染触发={POLLUTION_TRIGGER}次捕获 | 保底阈值={PITY_COUNTER_MAX}次 | 随机异色率={SHINY_DROP_RATE:.1%} | 牵手收益×{DOUBLE_REVENUE:.0f}',
         ha='center', va='center', fontsize=11, fontweight='bold', color='#555')

draw_rect(ax2, L, 11.2, NW, NH, '普通捕捉\n(球种A)', '#A8D8EA')
draw_diamond(ax2, M, 11.2, DW, DH, '捕捉成功?', '#FFF3CD')
draw_rect(ax2, R, 11.2, NW, NH, '失败', '#E0E0E0')
draw_sub(ax2, R, 10.35, SW, SH, '(无收益,球不返还)', '#E0E0E0')
arrow(ax2, L+NW/2, 11.2, M-DW/2, 11.2)
arrow(ax2, M, 11.2-DH/2, M, 9.8, '是')
arrow(ax2, M+DW/2, 11.2, R-NW/2, 11.2, '否')

arrow(ax2, R+NW/2, 10.5, R+NW/2+1.8, 10.5, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 10.5, R+NW/2+1.8, 12.0, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 12.0, L-NW/2, 12.0, '', 'dashed')
arrow(ax2, L-NW/2, 12.0, L-NW/2, 11.2, '', 'dashed')

draw_rect(ax2, L, 9.3, NW, NH, '获取精灵', '#C8E6C9')
draw_sub(ax2, L, 8.5, SW, SH, '(获得售价×2)', '#C8E6C9')
draw_rect(ax2, M, 9.3, NW, NH, '累计次数 +1', '#B2DFDB')
arrow(ax2, M, 10.2, M, 9.75)

draw_diamond(ax2, M, 7.4, DW+0.5, DH, f'累计≥{POLLUTION_TRIGGER}?', '#FFE0B2', 11)
draw_rect(ax2, R, 7.4, NW+0.5, NH, '否→继续\n普通捕捉', '#E0E0E0')
arrow(ax2, M, 8.85, M, 7.85)
arrow(ax2, M+DW/2, 7.4, R-NW/2, 7.4, '是')
arrow(ax2, M-DW/2, 7.4, L+NW/2, 7.4, '否')

arrow(ax2, L+NW/2, 7.4, L+NW/2+1.5, 7.4, '', 'dashed')
arrow(ax2, L+NW/2+1.5, 7.4, L+NW/2+1.5, 11.2, '', 'dashed')
arrow(ax2, L+NW/2+1.5, 11.2, L+NW/2, 11.2, '', 'dashed')

draw_rect(ax2, L, 5.2, NW, NH, '污染精灵出现', '#F8B4B4')
draw_sub(ax2, L, 4.4, SW, SH, '(消耗球种B)', '#F8B4B4')
draw_diamond(ax2, M, 5.2, DW, DH, '击破护盾?', '#C8E6C9')
draw_rect(ax2, R, 5.2, NW, NH, '未击破', '#E0E0E0')
draw_sub(ax2, R, 4.4, SW, SH, '(无收益,球不返还)', '#E0E0E0')

arrow(ax2, R-NW/2, 6.95, L+NW/2, 6.95, '', 'solid', '#888')
arrow(ax2, L+NW/2, 6.95, L+NW/2, 5.65, '', 'solid', '#888')
arrow(ax2, L+NW/2, 5.2, M-DW/2, 5.2)
arrow(ax2, M, 4.75, M, 3.9, '是')
arrow(ax2, M+DW/2, 5.2, R-NW/2, 5.2, '否')

arrow(ax2, R+NW/2, 4.5, R+NW/2+1.8, 4.5, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 4.5, R+NW/2+1.8, 11.2, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 11.2, L-NW/2-0.5, 11.2, '', 'dashed')

draw_rect(ax2, L, 3.2, NW, NH, '击破成功', '#B2DFDB')
draw_sub(ax2, L, 2.4, SW, SH, '(保底计数器+1)', '#B2DFDB')
draw_diamond(ax2, M, 3.2, DW, DH, '随机1.8%?', '#FFD54F')
draw_rect(ax2, R, 3.2, NW, NH, '是→获得异色', '#FFA07A')
draw_sub(ax2, R, 2.4, SW, SH, '(不消耗球)', '#FFA07A')

arrow(ax2, M, 3.85, M, 3.65)
arrow(ax2, M, 2.75, M, 2.0, '否')
arrow(ax2, M+DW/2, 3.2, R-NW/2, 3.2, '是')
arrow(ax2, M-DW/2, 3.2, L+NW/2, 3.2, '否')

draw_diamond(ax2, L, 1.2, DW+0.5, DH, f'计数≥{PITY_COUNTER_MAX}?', '#FFD54F', 10)
draw_rect(ax2, M, 1.2, NW, NH, '否→继续积累', '#E0E0E0')
draw_rect(ax2, R, 1.2, NW, NH, '保底触发!', '#FF6B6B')
draw_sub(ax2, R, 0.4, SW+0.4, SH+0.15, '必获异色,计数器清零', '#FF6B6B')

arrow(ax2, L, 1.65, L, 2.1)
arrow(ax2, L, 0.75, M-NW/2, 1.2, '否')
arrow(ax2, L+DW/2, 1.2, R-NW/2, 1.2, '是')

arrow(ax2, R+NW/2, 1.2, R+NW/2+1.8, 1.2, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 1.2, R+NW/2+1.8, 11.2, '', 'dashed')
arrow(ax2, R+NW/2+1.8, 11.2, L-NW/2-0.5, 11.2, '', 'dashed')

leg_x, leg_y = 1.8, 0.15
leg_items = [
    ('rect', '#B2DFDB', '矩形 = 操作/状态'),
    ('diamond', '#FFD54F', '菱形 = 判断/决策'),
    ('solid', '#333', '实线 = 主流程'),
    ('dashed', '#888', '虚线 = 循环/返回'),
]
for i, (typ, clr, txt) in enumerate(leg_items):
    lx = leg_x + i * 5.0
    if typ == 'rect':
        r = plt.Rectangle((lx-0.3, leg_y-0.14), 0.6, 0.28, fill=True,
                         facecolor=clr, edgecolor='#333', linewidth=1.5)
        ax2.add_patch(r)
    elif typ == 'diamond':
        d = plt.Polygon([(lx, leg_y+0.14), (lx+0.3, leg_y), (lx, leg_y-0.14), (lx-0.3, leg_y)],
                       fill=True, facecolor=clr, edgecolor='#333', linewidth=1.5)
        ax2.add_patch(d)
    else:
        ls = '--' if typ == 'dashed' else '-'
        ax2.plot([lx-0.35, lx+0.35], [leg_y, leg_y], color=clr, linewidth=2.5, linestyle=ls)
    ax2.text(lx+0.5, leg_y, txt, ha='left', va='center', fontsize=10, color='#444')

plt.tight_layout(pad=1.0)
plt.savefig('p3_fig2_流程图.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图2已保存: p3_fig2_流程图.png")

# 图3：收敛图
fig3, ax3 = plt.subplots(figsize=(12, 7))
x_axis = np.arange(1, len(avg_hist) + 1)
ax3.plot(x_axis, avg_hist, linewidth=0.6, alpha=0.5, color='#3B7DD8')
window = max(10, len(avg_hist) // 50)
smoothed = np.convolve(avg_hist, np.ones(window)/window, mode='valid')
ax3.plot(np.arange(window, len(avg_hist)+1), smoothed, color='#D32F2F',
         linewidth=2.2, label=f'滑动平均 (窗口={window})', zorder=5)
ax3.axhline(y=best_net, color='#2E7D32', linestyle='--', linewidth=2.5,
            label=f'理论值 = {best_net:,.0f}', zorder=4)
ax3.set_title('问题3：蒙特卡洛仿真收敛图\n(均值收敛至理论值，验证模型正确性)',
              fontsize=15, fontweight='bold', pad=16)
ax3.set_xlabel('尝试次数', fontsize=13, labelpad=8)
ax3.set_ylabel('平均净收益（洛克贝/次）', fontsize=13, labelpad=8)
ax3.legend(fontsize=10.5, loc='center right', framealpha=0.92, edgecolor='#CCCCCC')
ax3.grid(alpha=0.2, linestyle='--', linewidth=0.7)
ax3.tick_params(labelsize=10)
plt.tight_layout(pad=2.0)
plt.savefig('p3_fig3_收敛图.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图3已保存: p3_fig3_收敛图.png")

# 图4：保底计数器分布
counter_samples = []
pity_counter_sim = 0
captures_since = 0
ba_sim = BALLS_DATA[best_A]
bb_sim = BALLS_DATA[best_B]

for _ in range(200000):
    if np.random.random() < ba_sim['base_rate'] * r0:
        captures_since += 1
        if captures_since >= POLLUTION_TRIGGER:
            captures_since = 0
            if np.random.random() < bb_sim['base_rate']:
                pity_counter_sim += 1
                if pity_counter_sim >= PITY_COUNTER_MAX:
                    pity_counter_sim = 0
    counter_samples.append(pity_counter_sim)

fig4, ax4 = plt.subplots(figsize=(12, 7))
ax4.hist(counter_samples, bins=range(0, PITY_COUNTER_MAX+2), density=True,
         color='#3B7DD8', edgecolor='white', alpha=0.82, linewidth=0.5)
ax4.axvline(np.mean(counter_samples), color='#D32F2F', linestyle='--', linewidth=2.5,
            label=f'均值 = {np.mean(counter_samples):.1f}')
ax4.set_title('问题3：保底计数器稳态分布直方图\n(200,000步随机游走采样)',
              fontsize=15, fontweight='bold', pad=16)
ax4.set_xlabel('计数器值', fontsize=13, labelpad=8)
ax4.set_ylabel('概率密度', fontsize=13, labelpad=8)
ax4.legend(fontsize=11, loc='upper right', framealpha=0.92, edgecolor='#CCCCCC')
ax4.grid(alpha=0.15, axis='y', linestyle='--', linewidth=0.7)
ax4.tick_params(labelsize=10)
plt.tight_layout(pad=2.0)
plt.savefig('p3_fig4_计数器分布.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图4已保存: p3_fig4_计数器分布.png")

# ======================== 深度优化图表 ========================

# 图5：马尔可夫转移矩阵+稳态分布
P = np.zeros((PITY_COUNTER_MAX + 1, PITY_COUNTER_MAX + 1))
p_hit = BALLS_DATA[best_B]['base_rate']
for i in range(PITY_COUNTER_MAX):
    trans_p = p_hit * (1 / POLLUTION_TRIGGER) * (BALLS_DATA[best_A]['base_rate'] * r0)
    P[i, i] = 1 - trans_p
    P[i, i + 1] = trans_p
P[PITY_COUNTER_MAX, 0] = P[0, 1]
P[PITY_COUNTER_MAX, PITY_COUNTER_MAX] = 1 - P[PITY_COUNTER_MAX, 0]

# 【修正】使用幂迭代法代替特征值分解，数值更稳定
def power_iteration(P, max_iter=50000, tol=1e-14):
    """幂迭代法求马尔可夫链稳态分布 π = π·P"""
    n = P.shape[1]
    pi = np.ones(n) / n  # 均匀初始化
    for iteration in range(max_iter):
        pi_new = pi @ P
        delta = np.max(np.abs(pi_new - pi))
        pi = pi_new
        if delta < tol:
            print(f"  幂迭代收敛于第 {iteration + 1} 次迭代，δ = {delta:.2e}")
            break
    else:
        print(f"  警告：幂迭代未在 {max_iter} 次内收敛，最终 δ = {delta:.2e}")
    return pi

steady_state = power_iteration(P)

# 验证稳态性质：||πP - π||_∞ → 0
verification_error = np.max(np.abs(steady_state @ P - steady_state))
print(f"  稳态验证: ||πP - π||_∞ = {verification_error:.2e}")
print(f"  稳态概率和: {steady_state.sum():.10f}（应为 1.0）")
print(f"  稳态最小值: {steady_state.min():.6e}（应 ≥ 0）")

# 对比特征值方法（保留作为参考，不再作为主方法）
eigvals, eigvecs = np.linalg.eig(P.T)
steady_idx_eig = np.argmin(np.abs(eigvals - 1.0))
steady_state_eig = np.real(eigvecs[:, steady_idx_eig])
steady_state_eig = steady_state_eig / steady_state_eig.sum()
diff_two_methods = np.max(np.abs(steady_state - steady_state_eig))
print(f"  幂迭代 vs 特征值分解 最大差异: {diff_two_methods:.2e}")

fig5, (ax5a, ax5b) = plt.subplots(1, 2, figsize=(18, 8))

im5 = ax5a.imshow(P[:30, :30], cmap='YlOrRd', aspect='auto', interpolation='nearest', vmin=0, vmax=1)
ax5a.set_xlabel('下一状态计数器值', fontsize=12, labelpad=8)
ax5a.set_ylabel('当前状态计数器值', fontsize=12, labelpad=8)
ax5a.set_title(f'保底计数器马尔可夫转移矩阵\n(前30×30状态, {best_A}+{best_B})',
               fontsize=14, fontweight='bold', pad=14)
cbar5a = plt.colorbar(im5, ax=ax5a, label='转移概率', shrink=0.85, pad=0.02)
cbar5a.ax.tick_params(labelsize=9)

bars_steady = ax5b.bar(range(len(steady_state)), steady_state, color='#3B7DD8',
                       edgecolor='white', width=0.8, linewidth=0.5)
max_idx = np.argmax(steady_state)
ax5b.axvline(x=max_idx, color='#D32F2F', linestyle='--', linewidth=2.0)
ax5b.annotate(f'众数 = {max_idx}',
              xy=(max_idx, steady_state[max_idx]),
              xytext=(max_idx + 8, steady_state[max_idx] * 1.15),
              fontsize=11, color='#D32F2F', fontweight='bold',
              arrowprops=dict(arrowstyle='->', color='#D32F2F', lw=1.5),
              bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.9,
                       edgecolor='#CCCCCC'))
ax5b.set_xlabel('计数器值', fontsize=12, labelpad=8)
ax5b.set_ylabel('稳态概率', fontsize=12, labelpad=8)
ax5b.set_title(f'保底计数器稳态分布\n(E[计数]={np.sum(np.arange(len(steady_state))*steady_state):.1f}·众数={max_idx})',
               fontsize=14, fontweight='bold', pad=14)
ax5b.grid(axis='y', alpha=0.2, linestyle='--', linewidth=0.7)
ax5b.tick_params(labelsize=10)

fig5.suptitle('问题3：噩梦枷锁保底机制马尔可夫链分析', fontsize=16, fontweight='bold', y=1.02)
plt.tight_layout(pad=2.5)
plt.savefig('p3_fig5_马尔可夫链.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图5已保存: p3_fig5_马尔可夫链.png")

# 图6：期望累积异色数量
n_total_captures = np.arange(0, 2001, 20)
E_shiny_cumulative = []
for n_cap in n_total_captures:
    n_pollution = n_cap / POLLUTION_TRIGGER
    E_hits = n_pollution * BALLS_DATA[best_B]['base_rate']
    E_random_shiny = E_hits * SHINY_DROP_RATE
    E_pity_shiny = E_hits / PITY_COUNTER_MAX
    E_shiny_cumulative.append(E_random_shiny + E_pity_shiny)

fig6, ax6 = plt.subplots(figsize=(13, 8))
ax6.plot(n_total_captures, E_shiny_cumulative, '-', color='#3B7DD8', linewidth=3.0,
         label='总期望异色数', zorder=4)
ax6.plot(n_total_captures,
         [n / POLLUTION_TRIGGER * BALLS_DATA[best_B]['base_rate'] * SHINY_DROP_RATE for n in n_total_captures],
         '--', color='#4CAF50', linewidth=2.0, label='随机异色 (1.8%)', zorder=3, alpha=0.85)
ax6.plot(n_total_captures,
         [n / POLLUTION_TRIGGER * BALLS_DATA[best_B]['base_rate'] / PITY_COUNTER_MAX for n in n_total_captures],
         '--', color='#E8313A', linewidth=2.0, label='保底异色', zorder=3, alpha=0.85)
ax6.fill_between(n_total_captures, 0, E_shiny_cumulative, alpha=0.12, color='#3B7DD8', zorder=1)

ax6.set_xlabel('总成功捕获次数', fontsize=13, labelpad=8)
ax6.set_ylabel('期望累积异色精灵数量', fontsize=13, labelpad=8)
ax6.set_title(f'问题3：期望累积异色精灵数量增长曲线\n({best_A}+{best_B}·牵手×2)',
              fontsize=15, fontweight='bold', pad=16)
ax6.legend(fontsize=11, loc='upper left', framealpha=0.92, fancybox=True,
           edgecolor='#CCCCCC')
ax6.grid(alpha=0.2, linestyle='--', linewidth=0.7)
ax6.tick_params(labelsize=10)
ax6.ticklabel_format(style='plain', axis='y')
plt.tight_layout(pad=2.5)
plt.savefig('p3_fig6_异色累积.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图6已保存: p3_fig6_异色累积.png")

# 图7：策略对比+收益瀑布分解
E_normal_val = BALLS_DATA[best_A]['base_rate'] * r0 * get_e_price_demon(best_A) * DOUBLE_REVENUE
E_pol_tries = BALLS_DATA[best_A]['base_rate'] * r0 / POLLUTION_TRIGGER
E_shiny_val = E_pol_tries * BALLS_DATA[best_B]['base_rate'] * (SHINY_DROP_RATE + SHINY_PITY_RATE) * E_PRICE_SHINY * DOUBLE_REVENUE
total_cost_val = BALLS_DATA[best_A]['cost'] + E_pol_tries * BALLS_DATA[best_B]['cost']

fig7, (ax7a, ax7b) = plt.subplots(1, 2, figsize=(18, 8))

# 左图：策略对比
x7 = np.arange(2)
w7 = 0.45
bars7a = ax7a.bar(x7, [best_net, no_pity_net], w7, color=['#3B7DD8', '#E8913A'],
                  edgecolor='white', linewidth=1.5)

y7max = max(best_net, no_pity_net)
for bar, val in zip(bars7a, [best_net, no_pity_net]):
    txt_y = bar.get_height() + y7max * 0.025
    ax7a.text(bar.get_x() + bar.get_width()/2, txt_y,
              f'{val:,.0f}', ha='center', fontsize=13, fontweight='bold')
ax7a.set_xticks(x7)
ax7a.set_xticklabels(['专精保底\n(A=国王球\nB=高级球)', '无视保底\n(国王球随意)'],
                     fontsize=11)
ax7a.set_title('每次期望净收益对比', fontsize=15, fontweight='bold', pad=14)
ax7a.set_ylabel('洛克贝 / 次', fontsize=13, labelpad=8)
ax7a.set_ylim(0, y7max * 1.22)
ax7a.grid(axis='y', alpha=0.2, linestyle='--', linewidth=0.7)
ax7a.tick_params(labelsize=10)

# 右图：瀑布图
waterfall_items = ['正常收益', '异色收益', '球A成本', '球B成本', '= 净收益']
waterfall_vals = [E_normal_val, E_shiny_val, -BALLS_DATA[best_A]['cost'],
                  -E_pol_tries * BALLS_DATA[best_B]['cost'],
                  E_normal_val + E_shiny_val - BALLS_DATA[best_A]['cost'] - E_pol_tries * BALLS_DATA[best_B]['cost']]
wf_colors = ['#3B7DD8', '#FFD700', '#D32F2F', '#E8913A', '#2E7D32']

max_pos = max(v for v in waterfall_vals if v > 0)
min_neg = min(v for v in waterfall_vals if v < 0)
total_range = max_pos - min_neg
ax7b.set_ylim(min_neg * 1.6, max_pos * 1.35)

cumulative = 0
for i, (item, val, c) in enumerate(zip(waterfall_items, waterfall_vals, wf_colors)):
    if i < len(waterfall_items) - 1:
        if val >= 0:
            bottom = 0
            bar_h = val
        else:
            bottom = cumulative + val
            bar_h = abs(val)
        ax7b.bar(i, bar_h, 0.55, bottom=bottom, color=c,
                 edgecolor='white', linewidth=1.2, alpha=0.85)

        if val >= 0:
            txt_y = bottom + bar_h + total_range * 0.025
            va = 'bottom'
        else:
            txt_y = bottom - total_range * 0.03
            va = 'top'
        ax7b.text(i, txt_y, f'{val:+,.0f}', ha='center', va=va,
                 fontsize=11, fontweight='bold')
        cumulative += val
    else:
        bar = ax7b.bar(i, val, 0.55, color=c, edgecolor='#333333', linewidth=1.8, alpha=0.9)
        txt_y_final = val + total_range * 0.04 if val >= 0 else val - total_range * 0.04
        ax7b.text(i, txt_y_final, f'{val:+,.0f}', ha='center', va='bottom' if val >= 0 else 'top',
                 fontsize=12, fontweight='bold')

ax7b.set_xticks(range(len(waterfall_items)))
ax7b.set_xticklabels(waterfall_items, fontsize=10.5, fontweight='bold')
ax7b.axhline(y=0, color='#333333', linewidth=1.2, linestyle='-')
ax7b.set_title('专精保底策略·收益构成分解', fontsize=15, fontweight='bold', pad=14)
ax7b.grid(axis='y', alpha=0.2, linestyle='--', linewidth=0.7)
ax7b.ticklabel_format(style='plain', axis='y')
ax7b.tick_params(labelsize=10)

fig7.suptitle('问题3：保底策略深度对比', fontsize=17, fontweight='bold', y=1.02)
plt.tight_layout(pad=3.0)
plt.savefig('p3_fig7_策略分解.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图7已保存: p3_fig7_策略分解.png")

# ======================== 家族选择建议 ========================

POKEMON_DATA = [
    ('恶魔狼','恶魔狼',6000,0.75), ('月牙雪熊','月牙雪熊',4500,0.85),
    ('犀角鸟','犀角鸟',2400,0.90), ('绒绒','绒绒',2400,0.90),
    ('粉星仔','粉星仔',2400,0.90),
    ('治愈兔','治愈兔(低阶)',1800,0.95), ('治愈兔','治愈兔(中阶)',3150,0.90), ('治愈兔','治愈兔(高阶)',4500,0.85),
    ('奇丽草','奇丽草(低阶)',1800,0.95), ('奇丽草','奇丽草(中阶)',3150,0.90), ('奇丽草','奇丽草(高阶)',4500,0.85),
    ('大耳帽兜','大耳帽兜(低阶)',1800,0.95), ('大耳帽兜','大耳帽兜(中阶)',3150,0.90), ('大耳帽兜','大耳帽兜(高阶)',4500,0.85),
    ('拉特','拉特(低阶)',1800,0.95), ('拉特','拉特(高阶)',4500,0.85),
    ('呼呼猪','呼呼猪(低阶)',1800,0.95), ('呼呼猪','呼呼猪(高阶)',4500,0.85),
    ('格兰种子','格兰种子(低阶)',1200,1.0), ('格兰种子','格兰种子(中阶)',2100,0.95), ('格兰种子','格兰种子(高阶)',3000,0.90),
]

FAMILY_MAP = defaultdict(list)
for fam, form, price, rate in POKEMON_DATA:
    FAMILY_MAP[fam].append({'form': form, 'base_price': price, 'capture_rate': rate})

print("\n=== 各家族国王球期望净收益排名 ===")
family_rank = []
for fam, forms in FAMILY_MAP.items():
    avg_p = np.mean([f['base_price'] for f in forms])
    avg_r = np.mean([f['capture_rate'] for f in forms])
    e_price = avg_p * 5.0 * E_COLOR * E_MEDAL
    e_net = 1.0 * avg_r * e_price * DOUBLE_REVENUE - BALLS_DATA['国王球']['cost']
    family_rank.append((fam, e_net, avg_p, avg_r))
family_rank.sort(key=lambda x: x[1], reverse=True)
for fam, en, ap, ar in family_rank:
    print(f"  {fam}: 净收益={en:,.0f}, 均价={ap:,.0f}, 捕捉率={ar:.0%}")

print(f"\n推荐专精家族: {family_rank[0][0]}")

# ======================== CSV 导出 ========================

try:
    df_combo.to_csv('p3_AB组合矩阵.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p3_AB组合矩阵.csv —— 请关闭 Excel 后重试。")

family_df = pd.DataFrame(family_rank, columns=['家族', '期望净收益', '平均基础售价', '平均捕捉率'])
family_df['期望净收益'] = family_df['期望净收益'].round(0)
family_df['平均基础售价'] = family_df['平均基础售价'].round(0)
family_df['平均捕捉率'] = (family_df['平均捕捉率'] * 100).round(1).astype(str) + '%'
try:
    family_df.to_csv('p3_家族专精排名.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p3_家族专精排名.csv —— 请关闭 Excel 后重试。")

strategy_df = pd.DataFrame({
    '策略': ['专精保底', '无视保底'],
    '球种A': [best_A, '国王球'],
    '球种B': [best_B, '—'],
    '期望净收益(洛克贝/次)': [round(best_net, 2), round(no_pity_net, 2)],
})
try:
    strategy_df.to_csv('p3_策略对比.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p3_策略对比.csv —— 请关闭 Excel 后重试。")

print("\nCSV已导出: p3_AB组合矩阵.csv / p3_家族专精排名.csv / p3_策略对比.csv")
print("\n问题3 完成！")

