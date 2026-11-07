"""Context + stylometry fusion and independent sentence/document heads."""

import torch
from torch import nn

from backend.app.engines.ai_detection.pooling import sentence_pool


class Detector(nn.Module):
    def __init__(self, backbone, classes=2, fusion_dim=128):
        super().__init__()
        self.backbone = backbone
        hidden = backbone.config.hidden_size
        self.context = nn.Linear(2 * hidden, fusion_dim)
        self.style = nn.Linear(48, fusion_dim)
        self.fusion = nn.Sequential(nn.Linear(2 * fusion_dim, fusion_dim), nn.GELU())
        self.sentence_head = nn.Linear(fusion_dim, classes)
        self.document_head = nn.Linear(fusion_dim, classes)

    def representations(
        self, input_ids, attention_mask, sentence_token_mask, features, feature_valid_mask
    ):
        hidden = self.backbone(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        spans, valid = sentence_pool(hidden, sentence_token_mask, attention_mask)
        style = torch.cat(
            [
                features.masked_fill(~feature_valid_mask.bool(), 0),
                feature_valid_mask.to(features.dtype),
            ],
            -1,
        )
        fused = self.fusion(torch.cat([self.context(spans), self.style(style)], -1))
        return fused.masked_fill(~valid[:, :, None], 0), valid

    def classify(self, representations, valid, sentence_weights=None):
        weights = valid.to(representations.dtype)
        if sentence_weights is not None:
            weights = weights * sentence_weights
        document = (representations * weights[:, :, None]).sum(1) / weights.sum(1).clamp_min(1)[
            :, None
        ]
        return self.sentence_head(representations), self.document_head(document)

    def forward(self, **inputs):
        representations, valid = self.representations(**inputs)
        sentence, document = self.classify(representations, valid)
        return {
            "sentence_logits": sentence,
            "document_logits": document,
            "sentence_valid_mask": valid,
        }
