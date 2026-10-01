import struct

def _cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = sum(x*x for x in a) ** 0.5
    nb = sum(x*x for x in b) ** 0.5
    return dot / (na * nb) if na * nb > 0 else 0


def _load_emb(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob)//4}f", blob))
