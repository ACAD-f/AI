# -*- coding: utf-8 -*-
"""
合金钢抗拉强度（tensile_strength，MPa）回归预测程序。

研究目标
--------
用钢的化学成分与热处理工艺参数，预测其抗拉强度（UTS，MPa），
并比较多元线性回归与随机森林两种模型在"按钢种划分"测试集上的表现。

数据来源
--------
SteelBench v1.0 公开子集 steelbench_core_open.csv（1,360 条记录、25 个字段），
DOI: 10.5281/zenodo.18530558，许可 CC-BY 4.0。
原始文件保存在 data/ 目录，程序只读取、不修改、不补造数据。

变量与单位
----------
输入特征（11 个）：
    C、Mn、Si、Cr、Ni、Mo、V、Cu、Al —— 质量分数 wt.%；
    austenitize_T —— 奥氏体化温度，°C；
    temper_T      —— 回火温度，°C。
预测目标：
    tensile_strength —— 抗拉强度，MPa。
禁止使用的列：屈服强度、延伸率、断面收缩率、冲击功、硬度等其他力学性能，
以及钢种编号、数据来源、data_tier 等标识列——它们与目标同源或属于标签泄漏，
把它们当输入会得到虚假的高精度。

输出文件（均写入 results/ 目录）
------------------------------
    metrics.csv             —— 各模型在测试集及分 data_tier 子集上的 MAE、RMSE、R²；
    predictions.csv         —— 测试集逐样本的编号、来源、参考强度与预测强度；
    prediction_comparison.png —— 参考值与预测值散点图（含 y = x 参考线）；
    feature_importance.png  —— 随机森林特征重要性条形图。
"""

from pathlib import Path

import matplotlib

# 使用无界面后端，保证在没有图形界面的环境下也能保存图片
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

# 相对路径：从项目根目录运行，避免把本机绝对路径写进代码
DATA_FILE = Path("data") / "steelbench_core_open.csv"
RESULT_DIR = Path("results")

# 候选输入特征：9 个合金元素质量分数（wt.%）+ 2 个热处理温度（°C）
FEATURES = ["C", "Mn", "Si", "Cr", "Ni", "Mo", "V", "Cu", "Al", "austenitize_T", "temper_T"]
TARGET = "tensile_strength"  # 预测目标：抗拉强度，单位 MPa
GROUP = "grade_id"  # 分组列：钢种编号，用于按钢种划分训练集与测试集
TIER = "data_tier"  # 数据来源层级：emk_spec_verified / nims_measured / kaggle_measured

# 中文字体与负号显示设置，保证图中的中文标题、坐标轴标签正常显示
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_pipeline(model):
    """把缺失值填补与回归模型串成一个 Pipeline。

    缺失值只用中位数填补，并开启 add_indicator 记录"该值原本缺失"，
    这样不会把未知成分或未知温度硬填成物理上的 0（0 是有意义的质量分数）。
    填补器只在训练集上 fit，避免测试集信息泄漏到训练过程。
    """
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", model),
        ]
    )


def evaluate(y_true, y_pred):
    """计算三个回归评价指标。

    MAE  —— 平均绝对误差（MPa），直观反映平均偏差大小；
    RMSE —— 均方根误差（MPa），对大误差更敏感；
    R²   —— 决定系数，1 表示完美拟合，0 相当于只用均值预测，可为负。
    """
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = r2_score(y_true, y_pred)
    return mae, rmse, r2


def main():
    RESULT_DIR.mkdir(exist_ok=True)

    # ---------- 1. 读取原始数据并记录清洗前的规模 ----------
    raw = pd.read_csv(DATA_FILE)
    n_raw = len(raw)
    grade_raw = raw[GROUP].nunique()
    tier_raw = raw[TIER].value_counts()

    # ---------- 2. 数据清洗（只删不造，统一用布尔索引） ----------
    df = raw.copy()
    # 无效目标：抗拉强度缺失或不是正数（强度不可能 ≤ 0）的记录无法用于有监督回归
    n_bad_target = int((df[TARGET].isna() | (df[TARGET] <= 0)).sum())
    df = df[df[TARGET].notna() & (df[TARGET] > 0)]
    # 缺少 grade_id 的记录无法参与按钢种分组的划分与分组检查
    n_missing_grade = int(df[GROUP].isna().sum())
    df = df.dropna(subset=[GROUP])
    # 完全重复的记录会造成同一样本被重复计数
    n_dup = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    n_clean = len(df)
    grade_clean = df[GROUP].nunique()
    tier_clean = df[TIER].value_counts()

    # 打印清洗前后数量，便于核对"删了什么、删了多少"
    print(f"原始记录数: {n_raw}, 钢种数: {grade_raw}")
    print("原始 data_tier 分布:")
    print(tier_raw.to_string())
    print(f"目标值无效: {n_bad_target}, grade_id 缺失: {n_missing_grade}, 完全重复: {n_dup}")
    print(f"清洗后记录数: {n_clean}, 钢种数: {grade_clean}")
    print("清洗后 data_tier 分布:")
    print(tier_clean.to_string())

    # ---------- 3. 按钢种划分训练集/测试集 ----------
    # 用 GroupShuffleSplit 按 grade_id 分组：同一钢种的多条热处理记录只会落在一侧，
    # 避免"同钢种不同工艺"同时出现在训练集和测试集里导致指标虚高。
    # test_size=0.2 表示约 80% 的钢种进训练集、20% 的钢种进测试集。
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(df, groups=df[GROUP]))
    train_grades = set(df.loc[train_idx, GROUP])
    test_grades = set(df.loc[test_idx, GROUP])
    print(f"训练集: {len(train_idx)} 条 / {len(train_grades)} 个钢种")
    print(f"测试集: {len(test_idx)} 条 / {len(test_grades)} 个钢种")
    # 检查两组钢种确实没有交集（重叠数必须为 0）
    print(f"钢种重叠数: {len(train_grades & test_grades)}")

    # 训练集中整列完全缺失的特征无法提供任何信息，需要报告并排除；
    # 注意判断只在训练集上做，不能因为测试集有值就把该列留在模型里。
    features = [c for c in FEATURES if not df.loc[train_idx, c].isna().all()]
    dropped = [c for c in FEATURES if c not in features]
    print(f"训练集完全缺失而排除的列: {dropped if dropped else '无'}")

    # ---------- 4. 准备训练集、测试集 ----------
    train = df.loc[train_idx]
    test = df.loc[test_idx]
    y_train = train[TARGET].to_numpy()
    y_test = test[TARGET].to_numpy()

    # 两个对照模型：多元线性回归（可解释的基线）与随机森林（非线性集成模型，100 棵树）
    models = {
        "LinearRegression": LinearRegression(),
        "RandomForest": RandomForestRegressor(n_estimators=100, random_state=42),
    }

    # 预测结果先按列收集，最后一次性写成 predictions.csv
    predictions = {
        "heat_id": test["heat_id"].to_numpy(),  # 样本编号
        "grade_id": test[GROUP].to_numpy(),  # 钢种编号
        "data_tier": test[TIER].to_numpy(),  # 数据来源层级
        "source": test["source"].to_numpy(),  # 原始来源名称
        "tensile_strength_reference": y_test,  # 参考强度（实测或规范值，MPa）
    }
    metric_rows = []
    fitted = {}

    # ---------- 5. 训练与评价（只用训练集拟合，测试集不参与调参） ----------
    for name, estimator in models.items():
        pipe = build_pipeline(estimator)
        pipe.fit(train[features], y_train)
        pred = pipe.predict(test[features])
        fitted[name] = pipe
        predictions[f"prediction_{name}"] = pred

        # 全部测试集上的整体指标
        mae, rmse, r2 = evaluate(y_test, pred)
        metric_rows.append(
            {"model": name, "subset": "all", "n": len(y_test), "MAE_MPa": mae, "RMSE_MPa": rmse, "R2": r2}
        )
        print(f"\n[{name}] 全部测试集 n={len(y_test)}: MAE={mae:.2f} MPa, RMSE={rmse:.2f} MPa, R2={r2:.4f}")

        # 按 data_tier 分组统计：emk 是规范最低强度，nims/kaggle 是实测值，
        # 两类数据混在一起时整体指标会掩盖差异，所以必须分开报告。
        for tier in sorted(test[TIER].unique()):
            mask = test[TIER].to_numpy() == tier
            t_mae, t_rmse, t_r2 = evaluate(y_test[mask], pred[mask])
            metric_rows.append(
                {"model": name, "subset": tier, "n": int(mask.sum()), "MAE_MPa": t_mae, "RMSE_MPa": t_rmse, "R2": t_r2}
            )
            print(f"  {tier:20s} n={int(mask.sum()):3d}: MAE={t_mae:7.2f}, RMSE={t_rmse:7.2f}, R2={t_r2:7.4f}")

    # ---------- 6. 保存评价指标与逐样本预测 ----------
    # metrics.csv：model=模型名，subset=all 或某个 data_tier，n=样本数，其余为三个指标
    metrics = pd.DataFrame(metric_rows)[["model", "subset", "n", "MAE_MPa", "RMSE_MPa", "R2"]]
    metrics.to_csv(RESULT_DIR / "metrics.csv", index=False, encoding="utf-8-sig")
    # predictions.csv：测试集每个样本一行，含两个模型的预测强度（MPa）
    pd.DataFrame(predictions).to_csv(RESULT_DIR / "predictions.csv", index=False, encoding="utf-8-sig")

    # ---------- 7. 绘制"参考值-预测值"对比图 ----------
    # 点在 y = x 虚线上表示预测完全准确；点越贴近该线，模型越好。
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, (name, _) in zip(axes, models.items()):
        pred = predictions[f"prediction_{name}"]
        row = metrics[(metrics["model"] == name) & (metrics["subset"] == "all")].iloc[0]
        ax.scatter(y_test, pred, s=22, alpha=0.65, edgecolors="none", label="样本点")
        low = float(min(y_test.min(), pred.min()))
        high = float(max(y_test.max(), pred.max()))
        ax.plot([low, high], [low, high], "k--", lw=1.2, label="y = x")
        ax.set_xlabel("参考抗拉强度 (MPa)")
        ax.set_ylabel("预测抗拉强度 (MPa)")
        ax.set_title(f"{name}\nMAE={row.MAE_MPa:.1f} MPa, R²={row.R2:.3f}")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(alpha=0.3)
    fig.suptitle("测试集参考值与预测值对比（按 grade_id 划分）")
    fig.tight_layout()
    fig.savefig(RESULT_DIR / "prediction_comparison.png", dpi=150)
    plt.close(fig)

    # ---------- 8. 绘制随机森林特征重要性 ----------
    # 注意：add_indicator 额外产生的"缺失指示列"要合并回对应特征，
    # 否则特征名与重要性长度对不上；合并后各特征重要性之和仍为 1。
    rf = fitted["RandomForest"].named_steps["model"]
    imputer = fitted["RandomForest"].named_steps["imputer"]
    names = list(imputer.get_feature_names_out(features))
    raw_importance = pd.Series(rf.feature_importances_, index=names)
    merged = {}
    for name, value in raw_importance.items():
        if name.startswith("missingindicator_"):
            base = name[len("missingindicator_"):]
        elif name.endswith("_missing"):
            base = name[: -len("_missing")]
        else:
            base = name
        merged[base] = merged.get(base, 0.0) + float(value)
    importance = pd.Series(merged).sort_values()
    fig2, ax2 = plt.subplots(figsize=(7.5, 5))
    ax2.barh(importance.index, importance.to_numpy(), color="#3b6ea5")
    ax2.set_xlabel("特征重要性（不纯度减少）")
    ax2.set_ylabel("输入特征")
    ax2.set_title("随机森林特征重要性（100 棵树，random_state=42）")
    for y_pos, value in enumerate(importance.to_numpy()):
        ax2.text(value, y_pos, f" {value:.3f}", va="center", fontsize=8)
    ax2.grid(axis="x", alpha=0.3)
    fig2.tight_layout()
    fig2.savefig(RESULT_DIR / "feature_importance.png", dpi=150)
    plt.close(fig2)

    # ---------- 9. 控制台汇总 ----------
    print("\n结果已写入:", RESULT_DIR.resolve())
    print("特征重要性:")
    print(importance.sort_values(ascending=False).round(4).to_string())
    # 交叉表用来说明本次划分与数据集自带的 split 列无关（本次为重新划分，不是官方基准测试）
    print("\n清洗后各 data_tier 与 split 交叉:")
    print(pd.crosstab(df[TIER], df["split"]).to_string())


if __name__ == "__main__":
    main()
