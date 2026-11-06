"""Hardware-independent adaptive schedule and recoverable trial journal."""
import csv
import itertools
import json
import os
import random
from pathlib import Path

LEVELS = tuple(range(10, 91, 10))
PAIRS = tuple(itertools.combinations(LEVELS, 2))


class Schedule:
    WEIGHTS = {"Untested": 8, "Training": 3, "Difficult": 1,
               "Provisional": 6, "Confirmed": 0.5}

    def __init__(self, folder, seed, resume=""):
        self.folder = Path(folder)
        self.rng = random.Random(seed)
        self.rows = []
        self.stage = 0
        self.recent = []
        self.n = 0
        self.block = None
        self.remaining = 0
        self.pairs = {p: dict(status="Untested", window=[], until=0,
                              Training=[0, 0], Probe=[0, 0]) for p in PAIRS}
        if resume:
            saved = json.loads(Path(resume).read_text(encoding="utf-8"))
            if saved["subject"] != "Ivan" or saved["version"] != 1:
                raise ValueError("Incompatible Ivan checkpoint")
            for row in saved["trials"]:
                self.record(row)
            self.rng.setstate((saved["rng"][0], tuple(saved["rng"][1]), saved["rng"][2]))
            self.block = tuple(saved["block"]) if saved["block"] else None
            self.remaining = saved["remaining"]

    def select(self, probe_fraction):
        eligible = [p for p in PAIRS if p[1] - p[0] >= (30, 20, 10)[self.stage]]
        available = [p for p in eligible if self.pairs[p]["until"] <= self.n]
        if not available:
            raise RuntimeError("Ivan schedule has no eligible pairs outside cooldown.")
        if self.rng.random() < probe_fraction:
            fewest = min(self.pairs[p]["Probe"][1] for p in available)
            pair = self.rng.choice([p for p in available if self.pairs[p]["Probe"][1] == fewest])
            mode = "Probe"
        else:
            if not self.remaining or self.block not in available:
                self.block = self.rng.choices(
                    available, [self.WEIGHTS[self.pairs[p]["status"]] for p in available]
                )[0]
                self.remaining = self.rng.randint(3, 5)
            pair = self.block
            self.remaining -= 1
            mode = "Training"
        return pair, mode, self.rng.choice(("Right", "Left"))

    def record(self, row):
        self.rows.append(row)
        if row["Status"] not in ("Success", "Incorrect"):
            return
        correct = int(row["Status"] == "Success")
        pair = row["Ivan_Low"], row["Ivan_High"]
        state = self.pairs[pair]
        mode = row["Ivan_Mode"]
        state[mode][0] += correct
        state[mode][1] += 1
        if mode == "Probe":
            return
        self.n += 1
        self.recent.append(correct)
        if len(self.recent) > 60:
            del self.recent[0]
        status = state["status"]
        if status != "Confirmed":
            window = state["window"]
            window.append(correct)
            if status == "Provisional" and len(window) == 5:
                state["status"] = "Confirmed" if sum(window) >= 4 else "Training"
                window.clear()
            elif status != "Provisional" and len(window) == 10:
                score = sum(window)
                state["status"] = "Difficult" if score <= 4 else (
                    "Training" if score <= 7 else "Provisional"
                )
                if score <= 4:
                    state["until"] = self.n + 20
                window.clear()
        if self.stage < 2 and len(self.recent) >= (50, 60)[self.stage]:
            if sum(self.recent[-20:]) >= 16:
                self.stage += 1
                self.recent.clear()

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / "Ivan_checkpoint.json"
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(dict(subject="Ivan", version=1, trials=self.rows,
                           rng=self.rng.getstate(), block=self.block,
                           remaining=self.remaining), stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)

    def training_choices(self):
        return [int(row["Status"] == "Success") for row in self.rows
                if row["Ivan_Mode"] == "Training" and row["Status"] in ("Success", "Incorrect")]

    def summary(self):
        by_pair = []
        by_delta = []
        for (low, high), state in self.pairs.items():
            correct, n = state["Training"]
            by_pair.append(dict(low=low, high=high, correct=correct, n=n,
                                accuracy=correct / n if n else None, state=state["status"]))
        for delta in range(10, 81, 10):
            rows = [row for row in by_pair if row["high"] - row["low"] == delta]
            n = sum(row["n"] for row in rows)
            correct = sum(row["correct"] for row in rows)
            by_delta.append(dict(delta=delta, n=n, accuracy=correct / n if n else None))
        return dict(by_pair=by_pair, by_delta=by_delta, step=10, stage="ABC"[self.stage])

    def export(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        if self.rows:
            with (self.folder / "Ivan_all_trials.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in self.rows for key in row)))
                writer.writeheader()
                writer.writerows(self.rows)
        rows = [dict(subject="Ivan", low=p[0], high=p[1], delta=p[1]-p[0],
                     mode=mode, correct=s[mode][0],
                     n=s[mode][1], accuracy=s[mode][0]/s[mode][1] if s[mode][1] else None,
                     status=s["status"] if mode == "Training" else None,
                     window=s["window"] if mode == "Training" else None,
                     cooldown_remaining=max(0, s["until"] - self.n) if mode == "Training" else None)
                for p, s in self.pairs.items() for mode in ("Training", "Probe")]
        with (self.folder / "Ivan_pair_accuracy.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        (self.folder / "Ivan_summary.json").write_text(json.dumps(
            dict(subject="Ivan", stage="ABC"[self.stage], training_n=self.n, pairs=rows),
            indent=2), encoding="utf-8")

    def dashboard(self, figure):
        figure.clear()
        axes = figure.subplots(2, 2)
        figure.suptitle(f"Ivan | Stage {'ABC'[self.stage]} | Training n={self.n}")
        for ax, mode in zip(axes[1], ("Training", "Probe")):
            matrix = [[float("nan")] * 9 for _ in LEVELS]
            for (low, high), state in self.pairs.items():
                i, j = LEVELS.index(low), LEVELS.index(high)
                k, n = state[mode]
                matrix[i][j] = k / n if n else float("nan")
                ax.text(j, i, f"{k/n:.0%}\nn={n}" if n else "—\nn=0",
                        ha="center", va="center", fontsize=7)
            ax.imshow(matrix, vmin=0, vmax=1, cmap="YlGn")
            ax.set(xticks=range(9), yticks=range(9), xticklabels=LEVELS,
                   yticklabels=LEVELS, title=f"{mode} Pair Accuracy")
        for mode in ("Training", "Probe"):
            choices = [int(r["Status"] == "Success") for r in self.rows
                       if r["Ivan_Mode"] == mode and r["Status"] in ("Success", "Incorrect")]
            axes[0, 0].plot(range(1, len(choices)+1),
                            [sum(choices[max(0, i-20):i])/min(20, i)
                             for i in range(1, len(choices)+1)], label=mode)
            differences = range(10, 81, 10)
            counts = [[sum(s[mode][i] for p, s in self.pairs.items() if p[1]-p[0] == d)
                       for i in (0, 1)] for d in differences]
            axes[0, 1].plot(list(differences), [k/n if n else float("nan") for k,n in counts],
                            marker="o", label=mode)
        for ax, title in zip(axes[0], ("Recent 20 valid choices", "Accuracy by brightness difference")):
            ax.set(title=title, ylim=(0, 1.05))
            ax.legend()
        statuses = ("Untested", "Training", "Difficult", "Provisional", "Confirmed")
        counts = [sum(s["status"] == status for s in self.pairs.values()) for status in statuses]
        figure.text(0.5, 0.015, "  |  ".join(f"{k}: {n}" for k, n in zip(statuses, counts)),
                    ha="center")
        figure.tight_layout(rect=(0, 0.035, 1, 0.96))
