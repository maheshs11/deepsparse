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

# postprocessing adapted from huggingface/transformers

# Copyright 2021 The HuggingFace Team. All rights reserved.
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

"""
Pipeline implementation and pydantic models for zero-shot text classification task
with mnli models
"""


from typing import List, Optional, Type, Union, Generator

import numpy
from pydantic import BaseModel, Field
from transformers.tokenization_utils_base import PaddingStrategy, TruncationStrategy

from deepsparse.transformers.pipelines.zero_shot_text_classification import (
    ZeroShotTextClassificationInputBase,
    ZeroShotTextClassificationPipelineBase,
)
from deepsparse.pipelines import Splittable
from deepsparse.utils import numpy_softmax


__all__ = [
    "MnliTextClassificationConfig",
    "MnliTextClassificationInput",
    "MnliTextClassificationPipeline",
]


class MnliTextClassificationConfig(BaseModel):
    """
    Schema for configuration options when running zero shot with mnli
    """

    hypothesis_template: str = Field(
        description="A formattable template for wrapping around the provided "
        "labels to create an mnli hypothesis",
        default="This text is about {}",
    )
    entailment_index: int = Field(
        description="Index of mnli model outputs which denotes entailment", default=0
    )
    contradiction_index: int = Field(
        description="Index of mnli model outputs which denotes contradiction", default=2
    )
    multi_class: bool = Field(
        description="True if class probabilities are independent, default False",
        default=False,
    )


class MnliTextClassificationInput(ZeroShotTextClassificationInputBase, Splittable):
    """
    Schema for inputs to zero_shot_text_classification pipelines
    Each sequence and each candidate label must be paired and passed through
    the model, so the total number of forward passes is num_labels * num_sequences
    """

    labels: Union[None, List[List[str]], List[str], str] = Field(
        description="The set of possible class labels to classify each "
        "sequence into. Can be a single label, a string of comma-separated "
        "labels, or a list of labels."
    )
    hypothesis_template: Optional[str] = Field(
        description="A formattable template for wrapping around the provided "
        "labels to create an mnli hypothesis. If provided, overrides the template "
        "in the mnli config.",
        default=None,
    )
    multi_class: Optional[bool] = Field(
        description="True if class probabilities are independent, default False. "
        "If provided, overrides the multi_class value in the config.",
        default=None,
    )

    # TODO typehint, docstring
    def split(self, pipeline_labels: Union[List[str], None]) -> Generator["MnliTextClassificationInput", None, None]:
        if pipeline_labels is None and self.labels is None:
            raise ValueError(
                "You must provide either static labels during pipeline creation or "
                "dynamic labels at inference time"
            )
        sequences = self.sequences
        labels = pipeline_labels or self.labels
        hypothesis_template = self.hypothesis_template
        multi_class = self.multi_class

        if isinstance(sequences, str):
            sequences = [sequences]

        for sequence in sequences:
            for label in labels:
                yield MnliTextClassificationInput(
                    sequences=sequence,
                    labels=[label],
                    hypothesis_template=self.hypothesis_template,
                    multi_class=self.multi_class,
                )


class MnliTextClassificationPipeline(ZeroShotTextClassificationPipelineBase):
    def __init__(
        self,
        model_path: str,
        batch_size: Optional[int] = None,
        model_config: Optional[Union[MnliTextClassificationConfig, dict]] = None,
        labels: Optional[List] = None,
        **kwargs,
    ):
        self._config = self.parse_config(model_config)
        self._labels = self._parse_labels(labels)

        if self._labels and batch_size is not None and batch_size % len(self._labels) != 0:
            raise ValueError(
                f"if static labels are provided then batch_size {batch_size} must "
                f"be divisible by the number of labels {len(self._labels)} or None"
            )

        if not self._labels and batch_size is not None:
            raise ValueError(
                "if no static labels are provided then batch_size must be set to None"
            )

        kwargs.update({"batch_size": batch_size})
        super().__init__(model_path=model_path, **kwargs)

    @property
    def config_schema(self) -> Type[MnliTextClassificationConfig]:
        """
        Config schema the model_config argument must comply to
        """
        return MnliTextClassificationConfig

    @property
    def input_schema(self) -> Type[MnliTextClassificationInput]:
        """
        Input schema inputs using the mnli model scheme must comply to
        """
        return MnliTextClassificationInput

    def parse_inputs(self, *args, **kwargs) -> BaseModel:
        input_schema = super().parse_inputs(*args, **kwargs)
        input_schema.labels = self._parse_labels(input_schema.labels)

        return input_schema, {"pipeline_labels": self._labels}

    def process_inputs(
        self,
        inputs: MnliTextClassificationInput,
    ) -> List[numpy.ndarray]:
        """
        :param inputs: inputs to the pipeline
        :return: inputs of this model processed into a list of numpy arrays that
            can be directly passed into the forward pass of the pipeline engine
        """
        sequences = inputs.sequences
        labels = self._labels or inputs.labels
        hypothesis_template = (
            inputs.hypothesis_template
            if inputs.hypothesis_template is not None
            else self._config.hypothesis_template
        )
        multi_class = (
            inputs.multi_class
            if inputs.multi_class is not None
            else self._config.multi_class
        )
        if isinstance(sequences, str):
            sequences = [sequences]

        # check for absent labels
        if inputs.labels is None and self._labels is None:
            raise ValueError(
                "You must provide either static labels during pipeline creation or "
                "dynamic labels at inference time"
            )

        # check for conflicting labels
        if inputs.labels is not None and self._labels is not None:
            raise ValueError(
                "Found both static labels and dynamic labels at inference time. You "
                "must provide only one"
            )

        # check for correct size if static labels
        if self._labels and len(sequences) != self._batch_size // len(self._labels):
            raise ValueError(
                "If static labels are provided, then the number of sequences "
                f"{len(sequences)} must match batch_size divided by the number of "
                f"labels {self._batch_size // len(self._labels)}"
            )

        # check for invalid hypothesis template
        if hypothesis_template.format(labels[0]) == hypothesis_template:
            raise ValueError(
                f"The provided hypothesis_template {hypothesis_template} was not "
                "able to be formatted with the target labels. Make sure the "
                "passed template includes formatting syntax such as {} where "
                "the label should go."
            )

        sequence_pairs = []
        for sequence in sequences:
            sequence_pairs.extend(
                [[sequence, hypothesis_template.format(label)] for label in labels]
            )
        print(sequence_pairs)

        tokens = self.tokenizer(
            sequence_pairs,
            add_special_tokens=True,
            return_tensors="np",
            padding=PaddingStrategy.MAX_LENGTH.value,
            # tokenize only_first so that hypothesis (label) is not truncated
            truncation=TruncationStrategy.ONLY_FIRST.value,
        )

        postprocessing_kwargs = dict(
            sequences=inputs.sequences,  # do not include list wrapping
            candidate_labels=labels,
            multi_class=multi_class,
        )

        return self.tokens_to_engine_input(tokens), postprocessing_kwargs

    def process_engine_outputs(
        self,
        engine_outputs: List[numpy.ndarray],
        sequences: Union[str, List[str]],
        candidate_labels: List[str],
        multi_class: bool,
    ) -> BaseModel:
        """
        :param engine_outputs: list of numpy arrays that are the output of the mnli
            engine forward pass
        :param sequences: original sequences passed to inference
        :param candidate_labels: labels to match scores with
        :param multi_class: if True, calculate each class score independently from
            one another
        :return: outputs of engine post-processed into an object in the `output_schema`
            format of this pipeline
        """
        # reshape sequences
        num_sequences = 1 if isinstance(sequences, str) else len(sequences)
        reshaped_outputs = numpy.reshape(
            engine_outputs, (num_sequences, len(candidate_labels), -1)
        )

        # calculate scores
        if not multi_class:
            entailment_logits = reshaped_outputs[:, :, self._config.entailment_index]
            scores = numpy_softmax(entailment_logits, axis=1)
        else:
            entailment_contradiction_logits = reshaped_outputs[
                :, :, [self._config.entailment_index, self._config.contradiction_index]
            ]
            probabilities = numpy_softmax(entailment_contradiction_logits, axis=2)
            scores = probabilities[:, :, 0]

        # negate scores to perform reversed sort
        sorted_indexes = numpy.argsort(scores * -1, axis=1)
        labels = [
            numpy.array(candidate_labels)[sorted_indexes[i]].tolist()
            for i in range(num_sequences)
        ]
        label_scores = numpy.take_along_axis(scores, sorted_indexes, axis=1).tolist()

        # reduce dims if passed a string, not a list of strings
        if isinstance(sequences, str):
            labels = labels[0]
            label_scores = label_scores[0]

        return self.output_schema(
            sequences=sequences,
            labels=labels,
            scores=label_scores,
        )

    def _parse_labels(self, labels: Union[None, List[str], str]) -> List[str]:
        #If given a string of comma separated labels, parses values into a list
        #
        #:param labels: A string of comma separated labels or a list of labels
        #:return: a list of labels, parsed if originally in string form
        if isinstance(labels, str):
            labels = [label.strip() for label in labels.split(",") if label.strip()]
        return labels
