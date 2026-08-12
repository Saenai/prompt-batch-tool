from __future__ import annotations

from collections.abc import Iterable
from typing import Any
import tkinter as tk
from tkinter import ttk

from .model_catalog import ModelFamily, ParameterTier, group_model_families, group_parameter_tiers


class ModelSelector(ttk.Frame):
    """Filterable model picker with configurable family and parameter tiers."""

    def __init__(
        self,
        parent: tk.Misc,
        grouping: dict[str, Any],
        *,
        selected_models: Iterable[str] = (),
        filter_text: str = "",
        collapsed_families: Iterable[str] = (),
        collapsed_tiers: Iterable[str] = (),
    ) -> None:
        super().__init__(parent)
        self.grouping = grouping
        self.pending_models = set(selected_models)
        self.collapsed_families = set(collapsed_families)
        self.collapsed_tiers = set(collapsed_tiers)
        self.model_vars: dict[str, tk.BooleanVar] = {}
        self.model_labels: dict[str, str] = {}
        self.model_families: list[ModelFamily] = []
        self.parameter_tiers: dict[str, list[ParameterTier]] = {}
        self.family_counter_vars: dict[str, tk.StringVar] = {}
        self.tier_counter_vars: dict[str, tk.StringVar] = {}
        self.source_var = tk.StringVar(value="模型：尚未加载")
        self.filter_var = tk.StringVar(value=filter_text)
        self._build_widgets()
        self.filter_var.trace_add("write", lambda *_: self._render())

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, textvariable=self.source_var).grid(row=0, column=0, sticky="w")
        ttk.Entry(header, textvariable=self.filter_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(header, text="全选", command=lambda: self._set_visible(True)).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(header, text="清空", command=lambda: self._set_visible(False)).grid(row=0, column=3)

        model_box = ttk.Frame(self, relief="sunken", borderwidth=1)
        model_box.grid(row=1, column=0, sticky="nsew")
        model_box.rowconfigure(0, weight=1)
        model_box.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(model_box, highlightthickness=0)
        scrollbar = ttk.Scrollbar(model_box, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.inner = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width))
        self._bind_wheel(self.canvas)
        self._bind_wheel(self.inner)

    def set_loading(self) -> None:
        self.source_var.set("模型：加载中…")

    def load_models(self, models: list[tuple[str, str]], source: str) -> None:
        selected = set(self.selected_ids()) | self.pending_models
        self.pending_models.clear()
        self.model_labels = dict(models)
        self.model_vars = {model_id: tk.BooleanVar(value=model_id in selected) for model_id, _ in models}
        self.model_families = group_model_families(models, self.grouping)
        tiering = self.grouping.get("parameter_tiers", {})
        self.parameter_tiers = {
            family.key: group_parameter_tiers(list(family.models), tiering)
            for family in self.model_families
        }
        self.source_var.set(f"模型：{len(models)} 个（{source}）")
        self._render()

    def selected_ids(self) -> list[str]:
        return [model_id for model_id, variable in self.model_vars.items() if variable.get()]

    def state_payload(self) -> dict[str, Any]:
        return {
            "selected_models": self.selected_ids(),
            "model_filter": self.filter_var.get(),
            # Keep the original state keys so existing GUI state remains compatible.
            "collapsed_model_groups": sorted(self.collapsed_families),
            "collapsed_model_tiers": sorted(self.collapsed_tiers),
        }

    def _visible_ids(self) -> list[str]:
        needle = self.filter_var.get().strip().casefold()
        return [
            model_id
            for model_id, label in self.model_labels.items()
            if not needle or needle in model_id.casefold() or needle in label.casefold()
        ]

    def _render(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self.family_counter_vars.clear()
        self.tier_counter_vars.clear()
        visible = set(self._visible_ids())
        filtering = bool(self.filter_var.get().strip())
        if not visible:
            empty_label = ttk.Label(self.inner, text="没有匹配的模型")
            empty_label.pack(anchor="w", padx=8, pady=8)
            self._bind_wheel(empty_label)
            return

        for family in self.model_families:
            family_visible = [model_id for model_id, _ in family.models if model_id in visible]
            if not family_visible:
                continue
            collapsed = family.key in self.collapsed_families and not filtering
            header = ttk.Frame(self.inner)
            header.pack(fill="x", padx=5, pady=(5, 1))
            header.columnconfigure(1, weight=1)
            toggle = ttk.Button(header, text="▶" if collapsed else "▼", width=2,
                                command=lambda key=family.key: self._toggle_family(key))
            toggle.grid(row=0, column=0, sticky="w")
            counter = tk.StringVar()
            self.family_counter_vars[family.key] = counter
            family_label = ttk.Label(header, textvariable=counter)
            family_label.grid(row=0, column=1, sticky="w", padx=(5, 8))
            select_button = ttk.Button(header, text="全选", width=5,
                                       command=lambda key=family.key: self._set_family(key, True))
            select_button.grid(row=0, column=2, padx=(0, 3))
            clear_button = ttk.Button(header, text="清空", width=5,
                                      command=lambda key=family.key: self._set_family(key, False))
            clear_button.grid(row=0, column=3)
            for widget in (header, toggle, family_label, select_button, clear_button):
                self._bind_wheel(widget)

            if collapsed:
                continue
            for tier in self.parameter_tiers.get(family.key, []):
                tier_visible = [model_id for model_id, _ in tier.models if model_id in visible]
                if not tier_visible:
                    continue
                state_key = self._tier_state_key(family.key, tier.key)
                tier_collapsed = state_key in self.collapsed_tiers and not filtering
                tier_header = ttk.Frame(self.inner)
                tier_header.pack(fill="x", padx=(28, 5), pady=(2, 0))
                tier_header.columnconfigure(1, weight=1)
                tier_toggle = ttk.Button(tier_header, text="▶" if tier_collapsed else "▼", width=2,
                                         command=lambda key=state_key: self._toggle_tier(key))
                tier_toggle.grid(row=0, column=0, sticky="w")
                tier_counter = tk.StringVar()
                self.tier_counter_vars[state_key] = tier_counter
                tier_label = ttk.Label(tier_header, textvariable=tier_counter)
                tier_label.grid(row=0, column=1, sticky="w", padx=(5, 8))
                tier_select = ttk.Button(tier_header, text="全选", width=5,
                                         command=lambda f=family.key, t=tier.key: self._set_tier(f, t, True))
                tier_select.grid(row=0, column=2, padx=(0, 3))
                tier_clear = ttk.Button(tier_header, text="清空", width=5,
                                        command=lambda f=family.key, t=tier.key: self._set_tier(f, t, False))
                tier_clear.grid(row=0, column=3)
                for widget in (tier_header, tier_toggle, tier_label, tier_select, tier_clear):
                    self._bind_wheel(widget)

                if tier_collapsed:
                    continue
                for model_id in tier_visible:
                    label = self.model_labels[model_id]
                    text = model_id if label == model_id else f"{model_id}  —  {label}"
                    checkbutton = ttk.Checkbutton(
                        self.inner, text=text, variable=self.model_vars[model_id], command=self._refresh_counters
                    )
                    checkbutton.pack(anchor="w", fill="x", padx=(52, 8), pady=1)
                    self._bind_wheel(checkbutton)
        self._refresh_counters()

    def _refresh_counters(self) -> None:
        for family in self.model_families:
            counter = self.family_counter_vars.get(family.key)
            if counter is not None:
                selected = sum(bool(self.model_vars[model_id].get()) for model_id, _ in family.models)
                counter.set(f"{family.label}（已选 {selected}/{len(family.models)}）")
            for tier in self.parameter_tiers.get(family.key, []):
                counter = self.tier_counter_vars.get(self._tier_state_key(family.key, tier.key))
                if counter is not None:
                    selected = sum(bool(self.model_vars[model_id].get()) for model_id, _ in tier.models)
                    counter.set(f"{tier.label}（已选 {selected}/{len(tier.models)}）")

    def _toggle_family(self, family_key: str) -> None:
        if family_key in self.collapsed_families:
            self.collapsed_families.remove(family_key)
        else:
            self.collapsed_families.add(family_key)
        self._render()

    def _set_family(self, family_key: str, value: bool) -> None:
        visible = set(self._visible_ids())
        for family in self.model_families:
            if family.key == family_key:
                for model_id, _ in family.models:
                    if model_id in visible:
                        self.model_vars[model_id].set(value)
                break
        self._refresh_counters()

    @staticmethod
    def _tier_state_key(family_key: str, tier_key: str) -> str:
        return f"{family_key}/{tier_key}"

    def _toggle_tier(self, state_key: str) -> None:
        if state_key in self.collapsed_tiers:
            self.collapsed_tiers.remove(state_key)
        else:
            self.collapsed_tiers.add(state_key)
        self._render()

    def _set_tier(self, family_key: str, tier_key: str, value: bool) -> None:
        visible = set(self._visible_ids())
        for tier in self.parameter_tiers.get(family_key, []):
            if tier.key == tier_key:
                for model_id, _ in tier.models:
                    if model_id in visible:
                        self.model_vars[model_id].set(value)
                break
        self._refresh_counters()

    def _set_visible(self, value: bool) -> None:
        for model_id in self._visible_ids():
            self.model_vars[model_id].set(value)
        self._refresh_counters()

    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._scroll)
        widget.bind("<Button-4>", self._scroll)
        widget.bind("<Button-5>", self._scroll)

    def _scroll(self, event: tk.Event) -> str | None:
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return None
            magnitude = max(1, abs(delta) // 120)
            units = -magnitude if delta > 0 else magnitude
        self.canvas.yview_scroll(units, "units")
        return "break"
