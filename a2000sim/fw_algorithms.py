"""课程固件侧算法参考实现（用于"算法正确性"的无实物测试）。

出处标注：
- SYSCLOCK_HZ / SysTick [M-2 实测]：20.000MHz，SysTick 重装 399999 = 20ms
- PLL 换算 [M-2 + TivaWare sysctl.c _SysCtlFrequencyGet 语义]
- 滑动窗口平均 / 迟滞门限 / 线性标定 [PPT《如何提高ADC采样精度和稳定度》]
- COURSE_CAL [PPT 参考公式]（注意：那是课程组按其调理板实测的拟合值，
  用于框架演示；对新调理板应重新拟合，见 fit_linear）
"""

from __future__ import annotations

SYSCLOCK_HZ = 20_000_000  # [M-2] 实测系统时钟


def systick_reload(period_s: float = 0.02, clock_hz: int = SYSCLOCK_HZ) -> int:
    """SysTick 重装值 = clock×period − 1。实测对照：0.02s@20MHz → 399999 [M-2]。"""
    return int(clock_hz * period_s) - 1


def pll_sysclk(ref_hz: int = 16_000_000, mint: int = 30,
               q: int = 12, sysdiv: int = 1) -> dict:
    """TM4C129 PLL 时钟换算（fury 架构：VCO=ref×MINT，再 ÷Q ÷(PSYSDIV+1)）。

    实测对照 [M-2]：ref=PIOSC 16MHz, MINT=30, Q=12, PSYSDIV=1 → 20.000MHz；
    MOSC 25MHz 会给出 750MHz VCO（超出 320–480MHz 窗口，flag 出来）。
    """
    vco = ref_hz * mint
    fsys = vco / q / (sysdiv + 1)
    return {
        "vco_hz": vco,
        "sysclk_hz": fsys,
        "vco_in_spec": 320_000_000 <= vco <= 480_000_000,
        "ref": "PIOSC" if ref_hz == 16_000_000 else ("MOSC" if ref_hz == 25_000_000 else "?"),
    }


class SlidingWindowAverage:
    """滑动窗口平均 [PPT：建议窗口 50–100、采样间隔 1–10ms]。

    默认整数除法以对齐课程代码（i32Sums[i]/WINDOW_SIZE）；
    float_avg=True 时返回浮点均值（用于指标评估）。
    """

    def __init__(self, window: int = 50, fill: int = 0, float_avg: bool = False):
        if window <= 0:
            raise ValueError("window 必须 > 0")
        self.window = window
        self.float_avg = float_avg
        self.buf = [fill] * window
        self.index = 0
        self.sum = fill * window

    def add(self, sample: int) -> int | float:
        self.sum += sample - self.buf[self.index]
        self.buf[self.index] = sample
        self.index = (self.index + 1) % self.window
        if self.float_avg:
            return self.sum / self.window
        return self.sum // self.window


class HysteresisFilter:
    """迟滞门限 [PPT：门限取显示最低位的 1–2 倍]。"""

    def __init__(self, deadband: float | int):
        self.deadband = deadband
        self.value: float | int | None = None

    def feed(self, x: float | int) -> float | int:
        if self.value is None or abs(x - self.value) > self.deadband:
            self.value = x
        return self.value


def fit_linear(points: list[tuple[float, float]]) -> tuple[float, float]:
    """最小二乘拟合 y = a×x + b [PPT：优先线性公式补偿，显示读数 = a×ADC + b]。"""
    n = len(points)
    if n < 2:
        raise ValueError("至少需要 2 个标定点")
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        raise ValueError("标定点退化（x 全相同）")
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


def apply_linear(x: float, a: float, b: float) -> float:
    return a * x + b


# [PPT] 课程组调理板上的参考标定（mV 域）：演示"拟合→应用"框架用。
COURSE_CAL = {
    "voltage": (2.005, -1.141),
    "current": (1.002, -36.12),
}
