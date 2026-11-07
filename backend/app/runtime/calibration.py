"""Temperature scaling on held-out calibration examples only."""


def fit_temperature(logits, labels):
    import torch

    values = torch.tensor(logits, dtype=torch.float32)
    targets = torch.tensor(labels, dtype=torch.long)
    if values.ndim != 2 or len(values) != len(targets) or len(set(labels)) < 2:
        raise ValueError("Calibration needs matched logits and both labeled classes")
    log_temperature = torch.zeros((), requires_grad=True)
    optimizer = torch.optim.LBFGS([log_temperature], max_iter=50, line_search_fn="strong_wolfe")

    def closure():
        optimizer.zero_grad()
        temperature = log_temperature.exp().clamp(0.05, 100)
        loss = torch.nn.functional.cross_entropy(values / temperature, targets)
        loss.backward()
        return loss

    optimizer.step(closure)
    return float(log_temperature.detach().exp().clamp(0.05, 100))
