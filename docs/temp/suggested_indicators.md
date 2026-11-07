维度	候选指标 / 算法	备注
1. 趋势效率与质量	ER、Choppiness、VHF、回归 R²、回归斜率 / ATR、Aroon、分形维数（Katz/Higuchi）	ER/CHOP/VHF 三选一或二选一，改用不同窗口
2. 自适应均线	KAMA、FRAMA、VIDYA、ALMA、HMA、ZLEMA、McGinley、MAMA/FAMA	用"价格偏离 + 斜率 + 斜率变化"，不用均线绝对值
3. 统计性质 / 均值回归	滚动 Hurst、方差比（Lo-MacKinlay，多个 k）、滚动自相关（lag 1–5）、OU 半衰期、价格 z-score、百分位排名、排列熵	Hurst 窗口太短估计很噪，建议至少 100 根 bar；ADF 检验计算贵，慎用
4. 周期 / 滤波（Ehlers 体系）	Super Smoother、Roofing filter、Bandpass、Cyber Cycle、Decycler、Instantaneous Trendline、Fisher / Inverse Fisher、Laguerre RSI、Schaff Trend Cycle、主导周期、Kalman 趋势斜率	日线上"识别周期"噪声大，价值主要在滤波后的低滞后趋势/动量。先少量引入
5. 动量变体	TSI、KST、Coppock、Connors RSI、累计 RSI(2)、QQE、Squeeze（BB 收进 Keltner 内 + 动量）、Awesome Oscillator、Elder Ray、Vortex、RVI、12-1 动量、多窗口收益率、残差动量（扣除指数 beta）	Connors RSI 和累计 RSI(2) 偏短线均值回归，和常规 RSI(14) 信息不同
6. 波动率估计与结构	Parkinson、Garman-Klass、Rogers-Satchell、Yang-Zhang、短/长波动率比、波动率的波动率、波动率分位数、NR4/NR7（窄幅 K 线）、带宽分位、上行/下行半方差、滚动偏度/峰度、今日区间 / ATR	OHLC 估计比收盘到收盘的波动率更高效，是明显的新维度
7. 价格结构 / 位置	距 N 日高低点（含 52 周高点比例）、Donchian 位置、回撤深度、距高点天数、连涨/连跌天数及幅度、缺口 / ATR、隔夜与日内收益分解、实体/上下影线占比（K 线连续化）、inside/outside bar	隔夜 vs 日内分解对股票尤其有用。确认式摆动点（ZigZag / 分形）必须带确认延迟
8. 成交量与流动性	相对成交量、成交额排名、Amihud 非流动性、Corwin-Schultz 价差估计、CMF、Force Index、OBV 斜率、价量滚动相关、VWAP 偏离	ASX 小盘股流动性差异很大，这组特征同时能做 universe 过滤和成交可行性判断
9. 相对强弱与市场背景（截面）	相对 XJO 的超额收益、滚动 beta / 相关性、行业相对强弱、截面分位（动量/波动/成交量）、市场宽度（% 在 200 日线上方、新高新低比）、截面离散度、指数趋势与波动状态	单股指标没有"相对"信息，这一组往往对 LightGBM 帮助最大
10. 多周期	日线指标的周线版本（resample 后整体滞后一根避免前视），做日线策略的过滤条件	周线 ER / 趋势状态 / RSI 最常用