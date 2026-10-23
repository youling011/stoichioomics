from unittest import TestCase
import csv,io
import numpy as np
from backend.apps.stoichdb.sequence_viz.exports import safe,csv_response,NumericToken
class ExplicitBooleanExports(TestCase):
    def test_numpy_false_is_false_not_missing(self):
        self.assertIs(safe(np.bool_(False)),False);self.assertIs(safe(np.bool_(True)),True)
        response=csv_response([['on_front'],[np.bool_(False)],[np.bool_(True)]],'test')
        rows=list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))));self.assertEqual(rows,[['on_front'],['False'],['True']])
    def test_zero_and_negative_numeric_values_are_preserved(self):
        self.assertEqual(safe(np.float64(0)),0);self.assertEqual(safe(np.int64(-2)),-2)
    def test_metadata_formula_defense_keeps_original_numeric_tokens(self):
        self.assertEqual(safe('=formula'),"'=formula");self.assertEqual(safe(NumericToken('-2.50')),'-2.50')
