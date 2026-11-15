# Moneta 交易指标与特征目录报告 (Moneta Trading Indicators & Features Catalogue Report)

本报告详细列出了 `moneta` 项目中 `data` 文件夹下由 `metadata.duckdb` 管理的两个核心 Parquet 特征数据集：`ohlcv_1h_features`（1小时周期，共 **270** 个字段）与 `ohlcv_5m_features`（5分钟周期，共 **305** 个字段）中所包含的所有技术指标与衍生特征。

---

## 一、 基础 OHLCV 与数据集列 (Base Columns)

所有特征表均包含基础的市场价格、成交量与时间戳字段：
- `instrument`: 交易品种（如 `AUD_USD` 等）
- `time`: 时间戳（带时区）
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `volume`: 成交量
- `n_bars`: 柱数量 / 采样聚合计数

---

## 二、 移动平均与趋势指标 (Moving Averages & Trend)
覆盖多周期参数 `6, 12, 24, 60, 120`：
- **简单移动平均 (SMA)**: `sma_6`, `sma_12`, `sma_24`, `sma_60`, `sma_120`
- **指数移动平均 (EMA)**: `ema_6`, `ema_12`, `ema_24`, `ema_60`, `ema_120`
- **平均方向指数 (ADX)**: `adx_6`, `adx_12`, `adx_24`, `adx_60`, `adx_120`
- **Directional Movement (+DI / -DI)**: `plus_di_*`, `minus_di_*` (周期: 6, 12, 24, 60, 120)
- **阿隆指标 (Aroon)**: `aroon_up_*`, `aroon_down_*` (周期: 6, 12, 24, 60, 120)
- **唐奇安通道 (Donchian Channel)**: 
  - 上轨: `dc_upper_6`, `dc_upper_12`, `dc_upper_24`, `dc_upper_60`, `dc_upper_120`
  - 下轨: `dc_lower_6`, `dc_lower_12`, `dc_lower_24`, `dc_lower_60`, `dc_lower_120`
  - 中轨: `dc_mid_6`, `dc_mid_12`, `dc_mid_24`, `dc_mid_60`, `dc_mid_120`
  - 通道位置与距离: `dc_pos_*`, `dist_high_*`, `dist_low_*`

---

## 三、 MACD 指标 (Moving Average Convergence Divergence)
覆盖多周期组合 `6_24`, `12_60`, `24_120`：
- **MACD 线**: `macd_6_24`, `macd_12_60`, `macd_24_120`
- **信号线 (Signal)**: `macd_signal_6_24`, `macd_signal_12_60`, `macd_signal_24_120`
- **柱状图 (Histogram)**: `macd_hist_6_24`, `macd_hist_12_60`, `macd_hist_24_120`
- **ATR 归一化 MACD 柱状图**: `macd_hist_atr_6_24`, `macd_hist_atr_12_60`, `macd_hist_atr_24_120`

---

## 四、 抛物线转向指标 (Parabolic SAR)
参数配置: `0.02/0.2` 及 `0.01/0.1`：
- `psar_0p02_0p2`, `psar_dir_0p02_0p2`, `psar_dist_0p02_0p2`
- `psar_0p01_0p1`, `psar_dir_0p01_0p1`, `psar_dist_0p01_0p1`

---

## 五、 超级趋势指标 (Supertrend)
多周期参数 `6, 12, 24, 60, 120` 与乘数 `2, 3`：
- `st_6_2`, `st_dir_6_2`, `st_dist_6_2`
- `st_6_3`, `st_dir_6_3`, `st_dist_6_3`
- `st_12_2`, `st_dir_12_2`, `st_dist_12_2`
- `st_12_3`, `st_dir_12_3`, `st_dist_12_3`
- `st_24_2`, `st_dir_24_2`, `st_dist_24_2`
- `st_24_3`, `st_dir_24_3`, `st_dist_24_3`
- `st_60_2`, `st_dir_60_2`, `st_dist_60_2`
- `st_60_3`, `st_dir_60_3`, `st_dist_60_3`
- `st_120_2`, `st_dir_120_2`, `st_dist_120_2`
- `st_120_3`, `st_dir_120_3`, `st_dist_120_3`

---

## 六、 动量与震荡指标 (Oscillators & Momentum)
多周期参数 `6, 12, 24, 60, 120`：
- **相对强弱指数 (RSI)**: `rsi_6`, `rsi_12`, `rsi_24`, `rsi_60`, `rsi_120`
- **变动率 (ROC)**: `roc_6`, `roc_12`, `roc_24`, `roc_60`, `roc_120`
- **动量 (Momentum)**: `mom_6`, `mom_12`, `mom_24`, `mom_60`, `mom_120`
- **随机震荡指标 (Stochastic)**: `stoch_k_*`, `stoch_d_*` (周期: 6, 12, 24, 60, 120)
- **商品通道指数 (CCI)**: `cci_6`, `cci_12`, `cci_24`, `cci_60`, `cci_120`
- **威廉指标 (Williams %R)**: `willr_6`, `willr_12`, `willr_24`, `willr_60`, `willr_120`

---

## 七、 波动率与通道指标 (Volatility & Bands)
多周期参数 `6, 12, 24, 60, 120`：
- **真实波幅 (True Range)**: `tr`
- **平均真实波幅 (ATR)**: `atr_6`, `atr_12`, `atr_24`, `atr_60`, `atr_120`
- **ATR 百分比**: `atr_pct_6`, `atr_pct_12`, `atr_pct_24`, `atr_pct_60`, `atr_pct_120`
- **布林带 (Bollinger Bands)**: 
  - `bb_mid_*`, `bb_upper_*`, `bb_lower_*`, `bb_width_*`, `bb_pctb_*`
- **凯特纳通道 (Keltner Channels)**: 
  - `kc_mid_*`, `kc_upper_*`, `kc_lower_*`
- **挤压指标 (Squeeze)**: `sqz_on_*`
- **历史波动率 (Historical Volatility)**: `hv_6`, `hv_12`, `hv_24`, `hv_60`, `hv_120`

---

## 八、 市场体制与结构指标 (Market Regime & Structure)
- **效率比 (Efficiency Ratio, ER)**: `er_6`, `er_12`, `er_24`, `er_60`, `er_120`
- **震荡指标/Choppiness Index**: `chop_6`, `chop_12`, `chop_24`, `chop_60`, `chop_120`

---

## 九、 K线形态与成交量指标 (Bar & Volume Indicators)
- **K线几何特征**: 
  - `bar_body_ratio`（实体比例）
  - `bar_upper_wick_ratio`（上影线比例）
  - `bar_lower_wick_ratio`（下影线比例）
  - `bar_clv`（收盘位置值 Close Location Value）
- **成交量移动平均与相对成交量**: `vol_sma_*`, `vol_rel_*`, `vol_ratio_*`
- **资金流量指标 (MFI)**: `mfi_6`, `mfi_12`, `mfi_24`, `mfi_60`, `mfi_120`
- **蔡金资金流量 (CMF)**: `cmf_6`, `cmf_12`, `cmf_24`, `cmf_60`, `cmf_120`
- **成交量加权平均价 (VWAP)**: `vwap`

---

## 十、 均线距离、价差与跨期比例 (Spreads & Distances)
- **EMA 距离**: `ema_dist_6`, `ema_dist_12`, `ema_dist_24`, `ema_dist_60`, `ema_dist_120`
- **EMA 跨期价差**: `ema_spread_6_24`, `ema_spread_12_60`, `ema_spread_24_120`
- **成交量比例**: `vol_ratio_6_24`, `vol_ratio_12_60`, `vol_ratio_24_120`

---

## 十一、 时间与日历周期特征 (Calendar & Time Cyclical)
- `hour_sin`, `hour_cos`（小时周期正余弦编码）
- `dow_sin`, `dow_cos`（星期周期正余弦编码）
- `is_gap_bar`（跳空K线标志）
- `is_partial`（部分K线标志）
- `is_near_market_close`（接近收盘标志）

---

## 十二、 5分钟表独有的多周期高频/高层上下文特征 (Higher Timeframe H1 Context - `5m_features` 专有)
在 `ohlcv_5m_features` 中额外包含对高一级时间周期（1小时 H1）特征的关联映射（共 35 个高阶上下文特征）：
- **H1 EMA 距离**: `h1_ema_dist_6`, `h1_ema_dist_12`, `h1_ema_dist_24`, `h1_ema_dist_60`, `h1_ema_dist_120`
- **H1 ADX**: `h1_adx_6`, `h1_adx_12`, `h1_adx_24`, `h1_adx_60`, `h1_adx_120`
- **H1 RSI**: `h1_rsi_6`, `h1_rsi_12`, `h1_rsi_24`, `h1_rsi_60`, `h1_rsi_120`
- **H1 效率比 (ER)**: `h1_er_6`, `h1_er_12`, `h1_er_24`, `h1_er_60`, `h1_er_120`
- **H1 ATR 百分比**: `h1_atr_pct_6`, `h1_atr_pct_12`, `h1_atr_pct_24`, `h1_atr_pct_60`, `h1_atr_pct_120`
- **H1 超级趋势方向**: 
  - `h1_st_dir_6_2`, `h1_st_dir_6_3`
  - `h1_st_dir_12_2`, `h1_st_dir_12_3`
  - `h1_st_dir_24_2`, `h1_st_dir_24_3`
  - `h1_st_dir_60_2`, `h1_st_dir_60_3`
  - `h1_st_dir_120_2`, `h1_st_dir_120_3`

---
*注：上述所有特征均由 Moneta 项目的 DuckDB 元数据（`/home/ubuntu/work/moneta/data/metadata.duckdb`）进行索引与管理，底层以 Parquet 文件形式高效存储。*
