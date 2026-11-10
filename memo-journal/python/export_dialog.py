"""내보내기 창(4단계): 기간과 형식을 고른다."""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QRadioButton, QVBoxLayout,
)

from storage import Storage


def _qdate(d: dt.date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> dt.date:
    return dt.date(q.year(), q.month(), q.day())


class ExportDialog(QDialog):
    """기간: 전체 / 보고 있는 달 / 직접 지정.  형식: JSON(다른 PC로 옮기기·백업) / TXT(읽기용)."""

    def __init__(self, storage: Storage, current: dt.date, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.current = current
        self.setWindowTitle("내보내기")
        v = QVBoxLayout(self)

        box = QGroupBox("기간")
        bv = QVBoxLayout(box)
        self.all_radio = QRadioButton("전체")
        self.month_radio = QRadioButton(f"{current.year}년 {current.month}월만")
        self.custom_radio = QRadioButton("기간 지정")
        self.all_radio.setChecked(True)
        self.period_group = QButtonGroup(self)
        for r in (self.all_radio, self.month_radio, self.custom_radio):
            self.period_group.addButton(r)
            bv.addWidget(r)
        row = QHBoxLayout()
        first, last = storage.date_range() or (current, current)
        self.start_edit = QDateEdit(_qdate(first))
        self.end_edit = QDateEdit(_qdate(last))
        for e in (self.start_edit, self.end_edit):
            e.setCalendarPopup(True)
            e.setDisplayFormat("yyyy-MM-dd")
        row.addSpacing(22)
        row.addWidget(self.start_edit)
        row.addWidget(QLabel("~"))
        row.addWidget(self.end_edit)
        row.addStretch(1)
        bv.addLayout(row)
        v.addWidget(box)

        fbox = QGroupBox("형식")
        fv = QVBoxLayout(fbox)
        self.json_radio = QRadioButton("JSON 백업 — 다른 PC로 옮기거나 보관할 때 (굵게·밑줄, 속지 배치 포함)")
        self.text_radio = QRadioButton("TXT — 읽거나 붙여 넣을 때 (글자만, 다시 가져올 수 없음)")
        self.json_radio.setChecked(True)
        self.format_group = QButtonGroup(self)
        for r in (self.json_radio, self.text_radio):
            self.format_group.addButton(r)
            fv.addWidget(r)
        v.addWidget(fbox)

        self.count_label = QLabel()
        v.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("내보내기")
        self.buttons.button(QDialogButtonBox.Cancel).setText("취소")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)

        self.period_group.buttonToggled.connect(lambda *_: self._update())
        self.start_edit.dateChanged.connect(lambda *_: self._picked_dates())
        self.end_edit.dateChanged.connect(lambda *_: self._picked_dates())
        self._update()

    def _picked_dates(self) -> None:
        self.custom_radio.setChecked(True)  # 날짜를 건드리면 '기간 지정'으로
        self._update()

    def date_range(self) -> tuple[Optional[dt.date], Optional[dt.date]]:
        """(시작, 끝). 전체면 (None, None)."""
        if self.month_radio.isChecked():
            y, m = self.current.year, self.current.month
            return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])
        if self.custom_radio.isChecked():
            a, b = _pydate(self.start_edit.date()), _pydate(self.end_edit.date())
            return (a, b) if a <= b else (b, a)  # 거꾸로 넣어도 알아서
        return None, None

    def file_format(self) -> str:
        return "txt" if self.text_radio.isChecked() else "json"

    def count(self) -> int:
        return self.storage.page_count(*self.date_range())

    def _update(self) -> None:
        n = self.count()
        self.count_label.setText(f"내보낼 내용: {n}일치" if n else "이 기간에는 적은 내용이 없습니다.")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(n > 0)

    def default_name(self, now: dt.datetime) -> str:
        a, b = self.date_range()
        span = "전체" if a is None else f"{a:%Y%m%d}-{b:%Y%m%d}"
        return f"메모일지_{span}_{now:%Y%m%d}.{self.file_format()}"
