from __future__ import annotations

from collections import defaultdict, deque
import tkinter as tk
from tkinter import ttk

from .gpu_monitor import GpuSnapshot


class GpuMonitorPanel(ttk.LabelFrame):
    """Compact native Tk panel for current VRAM state and short history."""

    def __init__(self, parent, history_samples: int, selected_index: int | None = None) -> None:
        super().__init__(parent, text="GPU / VRAM", padding=8)
        self.history_samples = history_samples
        self.preferred_index = selected_index
        self.snapshots: dict[int, GpuSnapshot] = {}
        self.histories: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=history_samples))
        self.selector_var = tk.StringVar()
        self.detail_var = tk.StringVar(value="正在读取本机 NVIDIA GPU…")
        self.selector_to_index: dict[str, int] = {}

        self.columnconfigure(1, weight=1)
        self.selector = ttk.Combobox(self, textvariable=self.selector_var, state="readonly", width=34)
        self.selector.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.selector.bind("<<ComboboxSelected>>", lambda _event: self._render_selected())
        ttk.Label(self, textvariable=self.detail_var).grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(self, maximum=100, value=0)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 4))
        self.chart = tk.Canvas(self, height=54, highlightthickness=1, highlightbackground="#a0a0a0")
        self.chart.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.chart.bind("<Configure>", lambda _event: self._draw_history())

    def selected_index(self) -> int | None:
        return self.selector_to_index.get(self.selector_var.get())

    def set_disabled(self) -> None:
        self.selector.configure(state="disabled", values=())
        self.detail_var.set("已在 config/app.json 中禁用")
        self.progress.configure(value=0)
        self._draw_message("GPU 监视已禁用")

    def show_error(self, message: str) -> None:
        self.detail_var.set(message)
        if not self.snapshots:
            self.selector.configure(state="disabled", values=())
            self.progress.configure(value=0)
            self._draw_message("暂无 NVIDIA GPU 遥测")

    def update_snapshots(self, snapshots: list[GpuSnapshot]) -> None:
        current_index = self.selected_index()
        self.snapshots = {snapshot.index: snapshot for snapshot in snapshots}
        values: list[str] = []
        self.selector_to_index.clear()
        for snapshot in snapshots:
            label = f"GPU {snapshot.index} — {snapshot.name}"
            values.append(label)
            self.selector_to_index[label] = snapshot.index
            self.histories[snapshot.index].append(snapshot.memory_percent)
        self.selector.configure(state="readonly", values=values)

        target_index = current_index if current_index in self.snapshots else self.preferred_index
        selected_label = next(
            (label for label, index in self.selector_to_index.items() if index == target_index),
            values[0],
        )
        self.selector_var.set(selected_label)
        self.preferred_index = None
        self._render_selected()

    def _render_selected(self) -> None:
        index = self.selected_index()
        snapshot = self.snapshots.get(index) if index is not None else None
        if snapshot is None:
            return
        used_gib = snapshot.memory_used_mib / 1024
        total_gib = snapshot.memory_total_mib / 1024
        self.progress.configure(value=snapshot.memory_percent)
        self.detail_var.set(
            f"{used_gib:.1f} / {total_gib:.1f} GiB  "
            f"({snapshot.memory_percent:.1f}%) · GPU {snapshot.utilization_percent}% · {snapshot.temperature_celsius} °C"
        )
        self._draw_history()

    def _draw_message(self, message: str) -> None:
        self.chart.delete("all")
        width = max(1, self.chart.winfo_width())
        height = max(1, self.chart.winfo_height())
        self.chart.create_text(width / 2, height / 2, text=message, fill="#666666")

    def _draw_history(self) -> None:
        index = self.selected_index()
        values = list(self.histories.get(index, ())) if index is not None else []
        if not values:
            self._draw_message("等待 VRAM 历史数据")
            return
        self.chart.delete("all")
        width = max(2, self.chart.winfo_width())
        height = max(2, self.chart.winfo_height())
        padding = 4
        usable_width = max(1, width - padding * 2)
        usable_height = max(1, height - padding * 2)
        for percent in (25, 50, 75):
            y = padding + usable_height * (1 - percent / 100)
            self.chart.create_line(padding, y, width - padding, y, fill="#e3e3e3")
        denominator = max(1, self.history_samples - 1)
        points: list[float] = []
        start_slot = self.history_samples - len(values)
        for offset, value in enumerate(values):
            x = padding + usable_width * (start_slot + offset) / denominator
            y = padding + usable_height * (1 - value / 100)
            points.extend((x, y))
        if len(points) >= 4:
            self.chart.create_line(*points, fill="#3074b3", width=2, smooth=True)
        else:
            self.chart.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill="#3074b3")
