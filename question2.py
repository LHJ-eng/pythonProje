# ============================================================
# 问题2：计入随机倍率后的期望收益
# 运行方式：python question2.py
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

# ======================== 通用函数 ========================

def expected_talent_multiplier(fixed_talent=None):
    if fixed_talent is not None:
        return float(fixed_talent)
    return sum(mult * prob for _, mult, prob in TALENT_DATA)

def expected_color_multiplier(fixed_color=None):
    if fixed_color is not None:
        return float(fixed_color)
    return sum(mult * prob for _, mult, prob in COLOR_DATA)

def expected_medal_multiplier(n_sim=200000):
    medal_mults = {m[0]: m[1] for m in MEDAL_DATA}
    medal_weights = [m[2] for m in MEDAL_DATA]
    total_weight = sum(medal_weights)
    medal_probs = [w / total_weight for w in medal_weights]
    medal_names = [m[0] for m in MEDAL_DATA]

    total_mult = 0.0
    for _ in range(n_sim):
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
        total_mult += product_mult
    return total_mult / n_sim

def sample_talent_multiplier():
    r = np.random.random()
    cum = 0
    for _, mult, prob in TALENT_DATA:
        cum += prob
        if r < cum:
            return mult
    return 1.0

def sample_color_multiplier():
    r = np.random.random()
    cum = 0
    for _, mult, prob in COLOR_DATA:
        cum += prob
        if r < cum:
            return mult
    return 1.0

def sample_medal_multiplier():
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

def sample_pokemon_price(base_price, fixed_talent=None, fixed_color=None):
    t_mult = fixed_talent if fixed_talent is not None else sample_talent_multiplier()
    c_mult = fixed_color if fixed_color is not None else sample_color_multiplier()
    m_mult = sample_medal_multiplier()
    return base_price * t_mult * c_mult * m_mult

# ======================== 预计算 ========================

np.random.seed(42)
E_TALENT = expected_talent_multiplier()
E_COLOR = expected_color_multiplier()
E_MEDAL = expected_medal_multiplier(200000)

print("=" * 60)
print("问题2：计入随机倍率后的期望收益")
print("=" * 60)
print(f"\n期望倍率预计算：")
print(f"  E[天分] = {E_TALENT:.4f}")
print(f"  E[颜色] = {E_COLOR:.4f}")
print(f"  E[奖牌] = {E_MEDAL:.4f}")
print(f"  总期望倍率 = {E_TALENT * E_COLOR * E_MEDAL:.4f}")

# ======================== 计算 ========================

S0 = 6000
r0 = 0.75

E_price_normal = S0 * E_TALENT * E_COLOR * E_MEDAL
E_price_king = S0 * 5.0 * E_COLOR * E_MEDAL
E_price_prism = S0 * E_TALENT * 10.0 * E_MEDAL

print(f"\n期望售价：")
print(f"  普通球: {E_price_normal:,.0f} 洛克贝")
print(f"  国王球: {E_price_king:,.0f} 洛克贝")
print(f"  棱镜球: {E_price_prism:,.0f} 洛克贝")

talent_contrib = E_TALENT - 1.0
color_contrib = E_COLOR - 1.0
medal_contrib = E_MEDAL - 1.0
total_extra = talent_contrib + color_contrib + medal_contrib
print(f"\n各因子对期望倍率增量贡献：")
print(f"  天分: {talent_contrib:.4f} ({talent_contrib/total_extra*100:.1f}%)")
print(f"  颜色: {color_contrib:.4f} ({color_contrib/total_extra*100:.1f}%)")
print(f"  奖牌: {medal_contrib:.4f} ({medal_contrib/total_extra*100:.1f}%)")

ball_names = list(BALLS_DATA.keys())
results_p2 = []
for name in ball_names:
    ball = BALLS_DATA[name]
    cost = ball['cost']
    actual_rate = ball['base_rate'] * r0
    if name == '属性球':
        actual_rate *= P_MATCH

    if ball['fixed_talent'] is not None:
        e_price = S0 * ball['fixed_talent'] * E_COLOR * E_MEDAL
    elif ball['fixed_color'] is not None:
        e_price = S0 * E_TALENT * ball['fixed_color'] * E_MEDAL
    else:
        e_price = E_price_normal

    e_revenue = actual_rate * e_price
    e_net = e_revenue - cost

    results_p2.append({
        '球种': name, '成本': cost, '实际成功率': f"{actual_rate:.2%}",
        '期望售价': round(e_price, 2), '期望净收益': round(e_net, 2),
    })

df_p2 = pd.DataFrame(results_p2)
print("\n各球种期望净收益：")
print(df_p2.to_string(index=False))

optimal_ball_p2 = df_p2.loc[df_p2['期望净收益'].idxmax(), '球种']
optimal_net_p2 = df_p2['期望净收益'].max()
print(f"\n最优球种: {optimal_ball_p2}, 净收益: {optimal_net_p2:,.0f} 洛克贝/次")

king_net = df_p2[df_p2['球种'] == '国王球']['期望净收益'].values[0]
adv_net = df_p2[df_p2['球种'] == '高级球']['期望净收益'].values[0]
print(f"\n混合策略分析：")
print(f"  国王球净收益: {king_net:,.0f}")
print(f"  高级球净收益: {adv_net:,.0f}")
print(f"  线性组合 → 极值在边界 → 应固定使用{'国王球' if king_net > adv_net else '高级球'}")

# ======================== 图表 ========================

# 图1：双饼图——分离为两张独立图，避免拥挤
fig1a, ax1a = plt.subplots(figsize=(8, 8))
sizes_extra = [talent_contrib, color_contrib, medal_contrib]
labels_extra = [f'天分\n(+{talent_contrib:.2f})', f'颜色\n(+{color_contrib:.2f})', f'奖牌\n(+{medal_contrib:.2f})']
wedges1, texts1, autotexts1 = ax1a.pie(
    sizes_extra, labels=labels_extra, autopct='%1.1f%%',
    colors=['#FF6B6B', '#4ECDC4', '#45B7D1'],
    explode=(0.04, 0.04, 0.06), shadow=False,
    textprops={'fontsize': 12, 'fontweight': 'bold'},
    pctdistance=0.75, startangle=90)
for at in autotexts1:
    at.set_fontsize(11)
    at.set_fontweight('bold')
ax1a.set_title('各因子对期望倍率增量贡献', fontsize=15, fontweight='bold', pad=20)
plt.tight_layout(pad=1.5)
plt.savefig('p2_fig1a_因子贡献.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()

fig1b, ax1b = plt.subplots(figsize=(8, 8))
sizes_total = [S0, S0*talent_contrib, S0*color_contrib, S0*medal_contrib]
labels_total = [f'基础\n({S0:,})', f'天分增量\n({S0*talent_contrib:,.0f})',
                f'颜色增量\n({S0*color_contrib:,.0f})', f'奖牌增量\n({S0*medal_contrib:,.0f})']
wedges2, texts2, autotexts2 = ax1b.pie(
    sizes_total, labels=labels_total, autopct='%1.1f%%',
    colors=['#95E1D3', '#FF6B6B', '#4ECDC4', '#45B7D1'],
    explode=(0.05, 0.03, 0.03, 0.04), shadow=False,
    textprops={'fontsize': 12, 'fontweight': 'bold'},
    pctdistance=0.75, startangle=90)
for at in autotexts2:
    at.set_fontsize(11)
    at.set_fontweight('bold')
ax1b.set_title('期望售价各组成部分占比', fontsize=15, fontweight='bold', pad=20)
plt.tight_layout(pad=1.5)
plt.savefig('p2_fig1b_售价组成.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("\n图1a/1b已保存: p2_fig1a_因子贡献.png / p2_fig1b_售价组成.png")

# 图2：各球种期望净收益柱状图
fig2, ax2 = plt.subplots(figsize=(12, 7))
bar_colors = ['#FFD700' if n == optimal_ball_p2 else '#A0C4E8' for n in ball_names]
edge_colors = ['#B8860B' if n == optimal_ball_p2 else '#6A8CA8' for n in ball_names]
line_widths = [3.0 if n == optimal_ball_p2 else 1.5 for n in ball_names]

bars = ax2.bar(df_p2['球种'], df_p2['期望净收益'], color=bar_colors,
               edgecolor=edge_colors, linewidth=line_widths)

y_range = df_p2['期望净收益'].max() - df_p2['期望净收益'].min()
for bar, val in zip(bars, df_p2['期望净收益']):
    if val >= 0:
        text_y = bar.get_height() + y_range * 0.03
        va = 'bottom'
    else:
        text_y = bar.get_height() - y_range * 0.03
        va = 'top'
    ax2.text(bar.get_x() + bar.get_width()/2, text_y, f'{val:,.0f}',
             ha='center', va=va, fontsize=10.5, fontweight='bold')

ax2.axhline(y=0, color='#333333', linewidth=1.0, linestyle='-')
ax2.set_title('问题2：各球种期望净收益对比\n（计入随机倍率·恶魔狼·显示最优球种高亮）',
              fontsize=15, fontweight='bold', pad=16)
ax2.set_ylabel('期望净收益（洛克贝）', fontsize=13, labelpad=8)
ax2.grid(axis='y', alpha=0.25, linestyle='--', linewidth=0.7)
ax2.tick_params(axis='x', labelsize=11)
ax2.tick_params(axis='y', labelsize=10)
plt.tight_layout(pad=2.0)
plt.savefig('p2_fig2_球种对比.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图2已保存: p2_fig2_球种对比.png")

# 图3：蒙特卡洛售价分布直方图（10万次）
n_sim = 100000
sim_normal = [sample_pokemon_price(S0) for _ in range(n_sim)]
sim_king = [sample_pokemon_price(S0, fixed_talent=5) for _ in range(n_sim)]
sim_prism = [sample_pokemon_price(S0, fixed_color=10) for _ in range(n_sim)]

fig3, axes = plt.subplots(1, 3, figsize=(22, 7))

def optimized_hist(ax, data, title, color, q_low=0.005, q_high=0.995):
    data = np.array(data)
    p_low = np.percentile(data, q_low * 100)
    p_high = np.percentile(data, q_high * 100)
    mask = (data >= p_low) & (data <= p_high)
    data_filtered = data[mask]

    ax.hist(data_filtered, bins=120, density=True, alpha=0.78,
            color=color, edgecolor='white', linewidth=0.4)

    mean_val = np.mean(data_filtered)
    median_val = np.median(data_filtered)
    ax.axvline(mean_val, color='#D32F2F', linestyle='--', linewidth=2.2,
               label=f'均值 = {mean_val:,.0f}')
    ax.axvline(median_val, color='#2E7D32', linestyle=':', linewidth=2.2,
               label=f'中位数 = {median_val:,.0f}')

    ax.set_title(title, fontsize=14, fontweight='bold', pad=14)
    ax.set_xlabel('售价（洛克贝）', fontsize=12, labelpad=6)
    ax.set_ylabel('概率密度', fontsize=12, labelpad=6)
    ax.legend(fontsize=9.5, loc='upper right', framealpha=0.92, edgecolor='#CCCCCC')
    ax.ticklabel_format(style='plain', axis='x')
    ax.tick_params(axis='x', labelsize=9)
    ax.tick_params(axis='y', labelsize=9)
    ax.grid(alpha=0.15, axis='y', linestyle='--', linewidth=0.5)
    ax.set_xlim(p_low * 0.92, p_high * 1.08)

optimized_hist(axes[0], sim_normal, '普通球种\n(天分+颜色+奖牌随机)', '#3B7DD8')
optimized_hist(axes[1], sim_king, '国王球\n(天分固定×5)', '#FFD700')
optimized_hist(axes[2], sim_prism, '棱镜球\n(颜色固定×10)', '#9370DB')

fig3.suptitle('问题2：蒙特卡洛模拟（100,000次）·精灵售价分布·截断显示P0.5-P99.5',
              fontsize=15, fontweight='bold', y=1.01)
plt.tight_layout(pad=2.5, rect=[0, 0, 1, 0.94])
plt.savefig('p2_fig3_售价分布.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图3已保存: p2_fig3_售价分布.png")

print(f"\n蒙特卡洛结果（完整数据）：")
for name, data in [('普通球', sim_normal), ('国王球', sim_king), ('棱镜球', sim_prism)]:
    print(f"  {name}: 均值={np.mean(data):,.0f}, 中位数={np.median(data):,.0f}, "
          f"P95={np.percentile(data,95):,.0f}, P99={np.percentile(data,99):,.0f}")

# 图4：累积期望收益对比——标注改为参考线+端点标注，避免碰撞
N_range = np.arange(1, 101)
cum_king = N_range * king_net
cum_adv = N_range * adv_net

fig4, ax4 = plt.subplots(figsize=(14, 8))

ax4.plot(N_range, cum_king, '-', color='#FFD700', linewidth=3.0,
         label=f'国王球 ({king_net:,.0f}/次)', zorder=3)
ax4.plot(N_range, cum_adv, '-', color='#3B7DD8', linewidth=2.5,
         label=f'高级球 ({adv_net:,.0f}/次)', zorder=2)

ax4.fill_between(N_range, cum_king, cum_adv, alpha=0.18,
                 color='#2E7D32' if king_net > adv_net else '#D32F2F',
                 label='累积差值区域', zorder=1)

# 在右端点标差值（不阻塞曲线）
diff_N100 = cum_king[-1] - cum_adv[-1]
ax4.annotate(f'100次累积\n差值 = {diff_N100:+,.0f}',
             xy=(100, cum_king[-1]),
             xytext=(80, cum_king[-1] + diff_N100 * 0.25),
             fontsize=10, fontweight='bold', ha='center',
             bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                      alpha=0.9, edgecolor='#AAAAAA', linewidth=0.8),
             arrowprops=dict(arrowstyle='->', color='#555555', lw=1.3))

# N=50处参考虚线
ax4.axvline(x=50, color='#999999', linestyle=':', linewidth=1.2, alpha=0.7)
diff_N50 = cum_king[49] - cum_adv[49]
ax4.annotate(f'N=50\n差值={diff_N50:+,.0f}',
             xy=(50, cum_king[49]),
             xytext=(40, cum_king[49] - diff_N50 * 0.5),
             fontsize=9, fontweight='bold', ha='center',
             bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                      alpha=0.88, edgecolor='#BBBBBB', linewidth=0.7),
             arrowprops=dict(arrowstyle='->', color='#777777', lw=1.0))

ax4.set_title('问题2：国王球 vs 高级球 · 累积期望净收益对比',
              fontsize=15, fontweight='bold', pad=16)
ax4.set_xlabel('捕捉只数 N', fontsize=13, labelpad=8)
ax4.set_ylabel('累积期望净收益（洛克贝）', fontsize=13, labelpad=8)
ax4.legend(fontsize=11, loc='upper left', framealpha=0.92, edgecolor='#CCCCCC')
ax4.grid(alpha=0.2, linestyle='--', linewidth=0.7)
ax4.tick_params(labelsize=10)
max_y = max(cum_king[-1], cum_adv[-1])
ax4.set_ylim(-max_y * 0.02, max_y * 1.2)
ax4.set_xlim(0, 105)

plt.tight_layout(pad=2.5)
plt.savefig('p2_fig4_累积对比.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()
print("图4已保存: p2_fig4_累积对比.png")

# 图5：交互式箱线图
try:
    import plotly.graph_objects as go
    fig5 = go.Figure()
    plot_data = [
        (sim_normal, '普通球种', '#3B7DD8'),
        (sim_king, '国王球（天分×5）', '#FFD700'),
        (sim_prism, '棱镜球（颜色×10）', '#9370DB'),
    ]
    for data, name, color in plot_data:
        fig5.add_trace(go.Box(y=data, name=name, boxmean='sd',
                              marker_color=color, fillcolor=color,
                              line=dict(color='#333333', width=1.5)))
    fig5.update_layout(
        title=dict(text='问题2：不同球种捕获精灵售价箱线图（100,000次模拟）',
                   font=dict(size=16, family='SimHei')),
        yaxis_title='售价（洛克贝）',
        height=550,
        template='plotly_white',
        font=dict(size=12),
        showlegend=True,
        legend=dict(orientation='h', y=1.02, x=0.5, xanchor='center'),
        margin=dict(l=80, r=30, t=70, b=60)
    )
    fig5.write_html('p2_fig5_箱线图.html')
    print("图5已保存: p2_fig5_箱线图.html")
except Exception as e:
    print(f"Plotly失败（可忽略）: {e}")

# CSV 导出
try:
    pd.DataFrame({
        '因子': ['天分', '颜色', '奖牌'],
        '期望倍率': [E_TALENT, E_COLOR, E_MEDAL],
        '增量': [talent_contrib, color_contrib, medal_contrib],
        '贡献占比(%)': [talent_contrib/total_extra*100, color_contrib/total_extra*100, medal_contrib/total_extra*100]
    }).to_csv('p2_因子贡献率.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p2_因子贡献率.csv —— 请关闭 Excel 后重试。")

try:
    df_p2.to_csv('p2_球种期望净收益.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p2_球种期望净收益.csv —— 请关闭 Excel 后重试。")

mc_stats = []
for name, data in [('普通球', sim_normal), ('国王球', sim_king), ('棱镜球', sim_prism)]:
    mc_stats.append({
        '球种': name, '均值': np.mean(data), '中位数': np.median(data),
        'P1': np.percentile(data, 1), 'P5': np.percentile(data, 5),
        'P95': np.percentile(data, 95), 'P99': np.percentile(data, 99),
        '标准差': np.std(data),
    })
try:
    pd.DataFrame(mc_stats).to_csv('p2_蒙特卡洛统计.csv', index=False, encoding='utf-8-sig')
except PermissionError:
    print("⚠️  无法写入 p2_蒙特卡洛统计.csv —— 请关闭 Excel 后重试。")

print("\nCSV已导出: p2_因子贡献率.csv / p2_球种期望净收益.csv / p2_蒙特卡洛统计.csv")
print("\n问题2 完成！")
