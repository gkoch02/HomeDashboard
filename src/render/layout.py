# Canvas dimensions
WIDTH = 800
HEIGHT = 480

# Header
HEADER_H = 40
HEADER_Y = 0

# Top/bottom split: calendar on top (320px), info bar on bottom (120px)
_BOTTOM_H = 120
_BOTTOM_Y = HEIGHT - _BOTTOM_H  # 360

# Week view region (full width, top area)
WEEK_X = 0
WEEK_Y = HEADER_H
WEEK_W = WIDTH
WEEK_H = _BOTTOM_Y - HEADER_H  # 320

# Bottom bar sub-regions (horizontal: weather | birthdays | info)
WEATHER_X = 0
WEATHER_Y = _BOTTOM_Y
WEATHER_W = 300
WEATHER_H = _BOTTOM_H

BIRTHDAY_X = WEATHER_W
BIRTHDAY_Y = _BOTTOM_Y
BIRTHDAY_W = 220
BIRTHDAY_H = _BOTTOM_H

INFO_X = WEATHER_W + BIRTHDAY_W
INFO_Y = _BOTTOM_Y
INFO_W = WIDTH - WEATHER_W - BIRTHDAY_W  # 250
INFO_H = _BOTTOM_H

# Padding
PAD = 8
PAD_SM = 4
