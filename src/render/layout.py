# Canvas dimensions
WIDTH = 800
HEIGHT = 480

# Header
HEADER_H = 40
HEADER_Y = 0

# Divider below header
CONTENT_TOP = HEADER_H

# Top/bottom split: calendar on top, info bar on bottom
BOTTOM_H = 120
TOP_H = HEIGHT - HEADER_H - BOTTOM_H  # 320
BOTTOM_Y = HEADER_H + TOP_H

# Week view region (full width, top area)
WEEK_X = 0
WEEK_Y = CONTENT_TOP
WEEK_W = WIDTH
WEEK_H = TOP_H

# Bottom bar sub-regions (horizontal: weather | birthdays | info)
WEATHER_X = 0
WEATHER_Y = BOTTOM_Y
WEATHER_W = 300
WEATHER_H = BOTTOM_H

BIRTHDAY_X = WEATHER_W
BIRTHDAY_Y = BOTTOM_Y
BIRTHDAY_W = 220
BIRTHDAY_H = BOTTOM_H

INFO_X = WEATHER_W + BIRTHDAY_W
INFO_Y = BOTTOM_Y
INFO_W = WIDTH - WEATHER_W - BIRTHDAY_W  # 250
INFO_H = BOTTOM_H

# Week view internals
WEEK_HEADER_H = 32
WEEK_COL_COUNT = 7
WEEK_COL_W = WEEK_W // WEEK_COL_COUNT  # 114px; last column extended to fill remainder
WEEK_LAST_COL_W = WEEK_W - WEEK_COL_W * (WEEK_COL_COUNT - 1)  # 114 + 2 = 116px

# Week view: weekend "Date" section (lower 25% of body area)
WEEK_BODY_H = TOP_H - WEEK_HEADER_H  # 288px
WEEK_DATE_SECTION_H = WEEK_BODY_H // 2  # 144px  — large day-number panel on Sat/Sun

# Padding
PAD = 8
PAD_SM = 4

# Weather panel internals
WEATHER_ICON_X_OFFSET = PAD + 4  # 12px from panel left
WEATHER_TEMP_X_OFFSET = 78  # right of icon
WEATHER_DETAIL_X_OFFSET = 154  # right column (desc, hi/lo, feels/wind, sun)
WEATHER_CONTENT_Y_OFFSET = 28  # top of icon / temp row (row 1: description)
WEATHER_HILO_Y_OFFSET = WEATHER_CONTENT_Y_OFFSET + 14  # row 2: hi/lo (42px)
WEATHER_DETAIL3_Y_OFFSET = WEATHER_CONTENT_Y_OFFSET + 26  # row 3: feels-like + wind (54px)
WEATHER_DETAIL4_Y_OFFSET = WEATHER_CONTENT_Y_OFFSET + 38  # row 4: sunrise / sunset (66px)
# forecast strip hline is at y0+82; row 4 with regular(11) (~12px) ends at ~y0+78 — 4px margin
WEATHER_HUMID_Y_OFFSET = WEATHER_DETAIL3_Y_OFFSET  # kept for backward compat
WEATHER_FORECAST_H = 38  # height of forecast strip at bottom
WEATHER_ALERT_H = 15  # alert bar replaces humidity row when active
