# -*- coding: utf-8 -*-
"""골든 대조 공용 TestCase. 허용 오차는 golden_values.json의 _tolerance에서만 읽는다."""
import math
import unittest
import warnings

import _helpers as H

warnings.filterwarnings("ignore")


class GoldenCase(unittest.TestCase):
    golden = None
    tol = None

    @classmethod
    def setUpClass(cls):
        cls.golden = H.load_golden()
        cls.tol = cls.golden["_tolerance"]

    def assertGolden(self, actual, expected, tol_key, label=""):
        """expected None은 NaN(산출 불가)과 대응."""
        if expected is None:
            self.assertTrue(actual is None or (isinstance(actual, float) and math.isnan(actual)),
                            f"{label}: 기대 산출 불가, 실제 {actual}")
            return
        self.assertIsNotNone(actual, f"{label}: 실제 None")
        a = float(actual)
        self.assertFalse(math.isnan(a), f"{label}: 실제 NaN, 기대 {expected}")
        self.assertLessEqual(abs(a - float(expected)), self.tol[tol_key],
                             f"{label}: 실제 {a!r}, 골든 {expected!r}, 허용 {self.tol[tol_key]}")
