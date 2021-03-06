###############################################################################
#
# Copyright 2012 Pants Developers (see AUTHORS.txt)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################

import threading
import unittest

from pants.engine import Engine

class PantsTestCase(unittest.TestCase):
    _engine_thread = None

    def setUp(self, engine=None):
        if not engine:
            engine = Engine.instance()
        self._engine = engine
        self._engine_thread = threading.Thread(target=self._engine.start)
        self._engine_thread.start()

    def tearDown(self):
        self._engine.stop()
        if self._engine_thread:
            self._engine_thread.join(1.0)
