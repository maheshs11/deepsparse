# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abc import ABC, abstractmethod
from typing import Any, List


class SplittableSchema(ABC):
    """
    A contract that ensures implementing subclass objects(representing a batch
    size of b) can be split into a smaller List of objects each representing a input
    of batch size 1
    """

    @abstractmethod
    def split(self, *args, **kwargs) -> List[Any]:
        """
        Utility abstract method that subclasses must implement, the goal of
        this function is to take in a Schema object with a batch size b, and
        split it into a List b smaller Schema objects with batch size 1

        :return: A List of smaller objects each representing an input of
            batch-size 1
        """
        raise NotImplementedError


class JoinableSchema(ABC):
    """
    A contract that ensures multiple objects of the implementing subclass can be
    combined into one object representing a bigger batch size
    """

    @abstractmethod
    def join(self, *args, **kwargs) -> Any:
        """
        Utility abstract method that subclasses must implement, the goal of
        this function is to take in an Iterable of subclass objects and combine
        them into one object representing a bigger batch size

        :return: A JoinableSchema object that represents a bigger batch
        """
        raise NotImplementedError
