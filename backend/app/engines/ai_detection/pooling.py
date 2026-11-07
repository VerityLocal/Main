import torch


def sentence_pool(hidden, sentence_token_mask, attention_mask):
    mask = sentence_token_mask.bool() & attention_mask[:, None, :].bool()
    valid = mask.any(-1)
    weights = mask.to(hidden.dtype)
    mean = torch.einsum("bsl,blh->bsh", weights, hidden) / weights.sum(-1).clamp_min(1)[..., None]
    maximum = (
        hidden[:, None, :, :]
        .masked_fill(~mask[:, :, :, None], torch.finfo(hidden.dtype).min)
        .amax(2)
    )
    maximum = maximum.masked_fill(~valid[:, :, None], 0)
    return torch.cat([mean, maximum], -1), valid
