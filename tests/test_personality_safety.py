from types import SimpleNamespace
from unittest.mock import patch

import pytest

from d5lib import newclasses


def test_incomplete_template_rejected_before_replacing_personalities():
    existing = [{"id": 1, "voice_group": 101, "variant": 0},
                {"id": 2, "voice_group": 101, "variant": 1},
                {"id": 3, "voice_group": 135, "variant": 0}]
    table = SimpleNamespace(rows=existing.copy())
    with patch.object(newclasses, "_tables", return_value=(None, table)), \
         patch.object(newclasses, "_save") as save:
        with pytest.raises(ValueError, match="fewer than three personality rows"):
            newclasses.add_personalities(None, None, 1350, 1010, ["A", "B", "C"])
        assert table.rows == existing
        save.assert_not_called()
