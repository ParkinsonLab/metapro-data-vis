BASE_LUM = 50


def get_color(i: int, n: int) -> str:
    hue = int((360 / (n + 1)) * i)
    return f"hsl({hue} 75 {BASE_LUM})"
