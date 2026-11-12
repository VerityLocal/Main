"""Deduplicate equivalent regions per page without merging overlapping images."""

import math


def deduplicate_regions(page, tolerance=0.01):
    unique, buckets = [], {}
    for region in page.regions:
        box = region['bbox']
        if len(box) != 4 or not all(math.isfinite(x) for x in box):
            continue
        # Bucket by the first coordinate and examine neighboring buckets so a
        # near-duplicate on a rounding boundary is still found.
        key = math.floor(box[0]/tolerance)
        candidates = (other for bucket in (key-1, key, key+1) for other in buckets.get(bucket, []))
        if any(all(abs(a-b) <= tolerance for a,b in zip(box, other['bbox'])) for other in candidates):
            page.duplicate_regions_removed += 1
            continue
        unique.append(region)
        buckets.setdefault(key, []).append(region)
    page.regions = unique
