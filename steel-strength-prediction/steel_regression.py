# -*- coding: utf-8 -*-
"""合金钢抗拉强度预测（SteelBench v1.0 公开子集）。

用钢的化学成分与热处理温度预测抗拉强度 tensile_strength（MPa），
比较多元线性回归与随机森林在按钢种划分的测试集上的表现。
输入 data/steelbench_core_open.csv，结果写入 results/。
"""

from pathlib import Path

import matplotlib

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

# 相对路径：从项目根目录运行
DATA_FILE = Path("data") / "steelbench_core_open.csv"
RESULT_DIR = Path("results")

# 9 个合金元素质量分数（wt.%）+ 2 个热处理温度（°C）
FEATURES = ["C", "Mn", "Si", "Cr", "Ni", "Mo", "V", "Cu", "Al", "austenitize_T", "temper_T"]
TARGET = "tensile_strength"  # 预测目标：抗拉强度，MPa
GROUP = "grade_id"  # 钢种编号，用于分组划分
TIER = "data_tier"  # 数据来源层级

# 中文字体与负号显示
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def build_pipeline(model):
    """缺失值用中位数填补并保留缺失指示，只在训练集拟合。"""
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", model),
        ]
    )


def evaluate(y_true, y_pred):
    """返回 MAE（MPa）、RMSE（MPa）与 R²。"""
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = r2_score(y_true, y_pred)
    return mae, rmse, r2


def main():
    RESULT_DIR.mkdir(exist_ok=True)

    # 1. 读取原始数据，记录清洗前规模
    raw = pd.read_csv(DATA_FILE)
    n_raw = len(raw)
    grade_raw = raw[GROUP].nunique()
    tier_raw = raw[TIER].value_counts()

    # 2. 数据清洗：只删不造
    df = raw.copy()
    n_bad_target = int((df[TARGET].isna() | (df[TARGET] <= 0)).sum())
    df = df[df[TARGET].notna() & (df[TARGET] > 0)]
    n_missing_grade = int(df[GROUP].isna().sum())
    df = df.dropna(subset=[GROUP])
    n_dup = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    n_clean = len(df)
    grade_clean = df[GROUP].nunique()
    tier_clean = df[TIER].value_counts()

    print(f"原始记录数: {n_raw}, 钢种数: {grade_raw}")
    print("原始 data_tier 分布:")
    print(tier_raw.to_string())
    print(f"目标值无效: {n_bad_target}, grade_id 缺失: {n_missing_grade}, 完全重复: {n_dup}")
    print(f"清洗后记录数: {n_clean}, 钢种数: {grade_clean}")
    print("清洗后 data_tier 分布:")
    print(tier_clean.to_string())

    # 3. 按钢种分组划分训练集/测试集，避免同钢种跨集泄漏
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(df, groups=df[GROUP]))
    train_grades = set(df.loc[train_idx, GROUP])
    test_grades = set(df.loc[test_idx, GROUP])
    print(f"训练集: {len(train_idx)} 条 / {len(train_grades)} 个钢种")
    print(f"测试集: {len(test_idx)} 条 / {len(test_grades)} 个钢种")
    print(f"钢种重叠数: {len(train_grades & test_grades)}")

    # 训练集中整列缺失的特征无信息量，排除
    features = [c for c in FEATURES if not df.loc[train_idx, c].isna().all()]
    dropped = [c for c in FEATURES if c not in features]
    print(f"训练集完全缺失而排除的列: {dropped if dropped else '无'}")

    # 4. 准备训练集与测试集
    train = df.loc[train_idx]
    test = df.loc[test_idx]
    y_train = train[TARGET].to_numpy()
    y_test = test[TARGET].to_numpy()

    models = {
        "LinearRegression": LinearRegression(),
        "RandomForest": RandomForestRegressor(n_estimators=100, random_state=42),
    }

    predictions = {
        "heat_id": test["heat_id"].to_numpy(),
        "grade_id": test[GROUP].to_numpy(),
        "data_tier": test[TIER].to_numpy(),
        "source": test["source"].to_numpy(),
        "tensile_strength_reference": y_test,
    }
    metric_rows = []
    fitted = {}

    # 5. 只用训练集训练，在测试集评价
    for name, estimator in models.items():
        pipe = build_pipeline(estimator)
        pipe.fit(train[features], y_train)
        pred = pipe.predict(test[features])
        fitted[name] = pipe
        predictions[f"prediction_{name}"] = pred

        mae, rmse, r2 = evaluate(y_test, pred)
        metric_rows.append(
            {"model": name, "subset": "all", "n": len(y_test), "MAE_MPa": mae, "RMSE_MPa": rmse, "R2": r2}
        )
        print(f"\n[{name}] 全部测试集 n={len(y_test)}: MAE={mae:.2f} MPa, RMSE={rmse:.2f} MPa, R2={r2:.4f}")

        # 按 data_tier 分层报告，区分规范最低强度与实测值
        for tier in sorted(test[TIER].unique()):
            mask = test[TIER].to_numpy() == tier
            t_mae, t_rmse, t_r2 = evaluate(y_test[mask], pred[mask])
            metric_rows.append(
                {"model": name, "subset": tier, "n": int(mask.sum()), "MAE_MPa": t_mae, "RMSE_MPa": t_rmse, "R2": t_r2}
            )
            print(f"  {tier:20s} n={int(mask.sum()):3d}: MAE={t_mae:7.2f}, RMSE={t_rmse:7.2f}, R2={t_r2:7.4f}")

    # 6. 保存评价指标与逐样本预测
    metrics = pd.DataFrame(metric_rows)[["model", "subset", "n", "MAE_MPa", "RMSE_MPa", "R2"]]
    metrics.to_csv(RESULT_DIR / "metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(predictions).to_csv(RESULT_DIR / "predictions.csv", index=False, encoding="utf-8-sig")

    # 7. 参考值与预测值对比图，虚线 y = x 表示完全准确
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

    # 8. 随机森林特征重要性，缺失指示列合并回对应特征
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

    # 9. 控制台汇总
    print("\n结果已写入:", RESULT_DIR.resolve())
    print("特征重要性:")
    print(importance.sort_values(ascending=False).round(4).to_string())
    print("\n清洗后各 data_tier 与 split 交叉:")
    print(pd.crosstab(df[TIER], df["split"]).to_string())


if __name__ == "__main__":
    main()
