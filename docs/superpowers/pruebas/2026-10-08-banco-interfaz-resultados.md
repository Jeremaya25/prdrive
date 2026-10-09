# Banco de la interfaz: resultados (08/10/2026)

Resultados del banco temporal `banco/` (workflow `banco-ui.yml`), que eligió el frontend de la
especificación `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`. Runtime fijado
(python-build-standalone 3.14.8, Tk 9.0.4), 7 rondas intercaladas por máquina, mediana (mín, máx).
Las capturas (`CAPTURA`) prueban que cada máquina pintó las ventanas de verdad.

- Windows x64 y ARM64: [run 37819787281](https://github.com/Jeremaya25/prdrive/actions/runs/37819787281)
- Linux x64 (repetido con las bibliotecas de Qt): [run 37820705305](https://github.com/Jeremaya25/prdrive/actions/runs/37820705305)

## windows-x64

```
windows-x64 qt-pyside6 cold-parejas 545.0 ms (min 525.2, max 659.9, n 7, rss 92.3)
windows-x64 qt-pyside6 open-parejas 102.6 ms (min 96.3, max 122.1, n 7, rss 92.5)
windows-x64 qt-pyside6 start-main 440.1 ms (min 426.9, max 511.0, n 7, rss 76.1)
windows-x64 qt-pyside6 switch-pane 18.7 ms (min 18.5, max 19.9, n 7, rss 82.8)
windows-x64 qt-pyside6 x-start-main-canned 333.3 ms (min 314.3, max 357.1, n 7, rss 63.0)
windows-x64 tk-065 cold-parejas 827.5 ms (min 804.6, max 864.7, n 7, rss 53.8)
windows-x64 tk-065 open-ajustes 159.0 ms (min 152.1, max 167.2, n 7, rss 52.0)
windows-x64 tk-065 open-parejas 200.9 ms (min 196.9, max 213.2, n 7, rss 53.8)
windows-x64 tk-065 start-agente 476.7 ms (min 472.2, max 549.4, n 7, rss 45.6)
windows-x64 tk-065 start-main 616.4 ms (min 604.9, max 648.7, n 7, rss 49.7)
windows-x64 tk-065 start-wizard 524.2 ms (min 516.0, max 579.3, n 7, rss 50.4)
windows-x64 tk-071 cold-parejas 2170.3 ms (min 2153.2, max 2427.9, n 7, rss 66.9)
windows-x64 tk-071 open-ajustes 231.6 ms (min 225.2, max 250.7, n 7, rss 66.1)
windows-x64 tk-071 open-parejas 837.3 ms (min 825.8, max 954.4, n 7, rss 66.9)
windows-x64 tk-071 start-agente 1035.6 ms (min 1002.6, max 1188.9, n 7, rss 57.5)
windows-x64 tk-071 start-main 1332.2 ms (min 1322.5, max 1471.4, n 7, rss 61.4)
windows-x64 tk-071 start-wizard 1217.5 ms (min 1198.2, max 1408.2, n 7, rss 61.9)
windows-x64 tk-071 switch-pane 211.8 ms (min 206.7, max 219.2, n 7, rss 66.6)
windows-x64 tk-071-dpi150 cold-parejas 2884.2 ms (min 2791.6, max 3146.0, n 7, rss 71.3)
windows-x64 tk-071-dpi150 open-ajustes 338.5 ms (min 332.1, max 384.6, n 7, rss 71.4)
windows-x64 tk-071-dpi150 open-parejas 1240.6 ms (min 1208.7, max 1361.8, n 7, rss 71.3)
windows-x64 tk-071-dpi150 start-main 1634.8 ms (min 1580.6, max 1816.2, n 7, rss 64.0)
windows-x64 tk-071-dpi150 switch-pane 309.9 ms (min 306.5, max 341.4, n 7, rss 72.0)
windows-x64 tk-071-pngcache cold-parejas 1418.8 ms (min 1384.7, max 1452.7, n 7, rss 67.8)
windows-x64 tk-071-pngcache open-ajustes 171.2 ms (min 164.2, max 177.1, n 7, rss 65.7)
windows-x64 tk-071-pngcache open-parejas 729.4 ms (min 717.6, max 749.4, n 7, rss 67.8)
windows-x64 tk-071-pngcache start-agente 391.9 ms (min 382.0, max 445.3, n 7, rss 57.1)
windows-x64 tk-071-pngcache start-main 681.9 ms (min 665.2, max 705.4, n 7, rss 62.2)
windows-x64 tk-071-pngcache start-wizard 595.5 ms (min 587.7, max 677.4, n 7, rss 62.0)
windows-x64 tk-071-pngcache switch-pane 180.3 ms (min 176.8, max 186.9, n 7, rss 66.3)
windows-x64 tk-bare start-bare 129.8 ms (min 127.7, max 145.6, n 7, rss 31.9)
windows-x64 tk-flat cold-parejas 335.3 ms (min 333.5, max 389.6, n 7, rss 38.4)
windows-x64 tk-flat open-parejas 159.4 ms (min 155.9, max 190.4, n 7, rss 39.9)
windows-x64 tk-flat start-main 258.1 ms (min 251.7, max 304.3, n 7, rss 35.1)
windows-x64 tk-widgets drawn-150 244.4 ms (min 240.4, max 252.9, n 7, rss 53.4)
windows-x64 tk-widgets drawn-300 442.6 ms (min 440.2, max 459.2, n 7, rss 54.7)
windows-x64 tk-widgets drawn-50 133.8 ms (min 126.2, max 138.9, n 7, rss 52.7)
windows-x64 tk-widgets plain-150 195.1 ms (min 192.9, max 204.1, n 7, rss 33.7)
windows-x64 tk-widgets plain-300 361.7 ms (min 351.7, max 372.8, n 7, rss 35.0)
windows-x64 tk-widgets plain-50 104.0 ms (min 97.7, max 108.6, n 7, rss 32.9)
captura windows-x64 tk-071 main ok=True 515x620 colores=164 printwindow=136 
captura windows-x64 tk-071 parejas ok=True 1002x1002 colores=579 printwindow=291 
captura windows-x64 tk-071 ajustes ok=True 977x627 colores=203 printwindow=148 
captura windows-x64 tk-071 wizard ok=True 885x650 colores=140 printwindow=100 
captura windows-x64 tk-071 agente ok=True 494x326 colores=111 printwindow=85 
captura windows-x64 tk-071-pngcache main ok=True 515x620 colores=164 printwindow=136 
captura windows-x64 tk-071-pngcache parejas ok=True 1002x1002 colores=579 printwindow=291 
captura windows-x64 tk-071-dpi150 main ok=True 789x882 colores=213 printwindow=160 
captura windows-x64 tk-071-dpi150 parejas ok=True 1510x947 colores=358 printwindow=281 
captura windows-x64 tk-071-dpi150 ajustes ok=True 1462x921 colores=249 printwindow=182 
captura windows-x64 tk-065 main ok=True 506x567 colores=151 printwindow=124 
captura windows-x64 tk-065 parejas ok=True 1044x608 colores=320 printwindow=178 
captura windows-x64 tk-065 ajustes ok=True 629x857 colores=152 printwindow=97 
captura windows-x64 tk-065 wizard ok=True 877x615 colores=136 printwindow=91 
captura windows-x64 tk-065 agente ok=True 482x288 colores=142 printwindow=60 
captura windows-x64 tk-flat main ok=True 537x662 colores=189 printwindow=145 
captura windows-x64 tk-flat parejas ok=True 1087x1022 colores=348 printwindow=280 
captura windows-x64 qt-pyside6 main ok=True 533x608 colores=331 printwindow=211 
captura windows-x64 qt-pyside6 parejas ok=True 1094x962 colores=658 printwindow=589 
captura windows-x64 qt-pyside6 ajustes ok=True 978x625 colores=331 printwindow=269 
```

## windows-arm64

```
windows-arm64 qt-pyside6 cold-parejas 483.0 ms (min 478.1, max 490.2, n 7, rss 93.1)
windows-arm64 qt-pyside6 open-parejas 74.6 ms (min 73.7, max 76.8, n 7, rss 93.5)
windows-arm64 qt-pyside6 start-main 392.3 ms (min 389.3, max 397.9, n 7, rss 79.9)
windows-arm64 qt-pyside6 switch-pane 19.5 ms (min 18.9, max 19.8, n 7, rss 86.6)
windows-arm64 qt-pyside6 x-start-main-canned 287.3 ms (min 285.9, max 290.4, n 7, rss 66.5)
windows-arm64 tk-065 cold-parejas 843.8 ms (min 833.1, max 846.1, n 7, rss 55.9)
windows-arm64 tk-065 open-ajustes 155.6 ms (min 154.6, max 159.7, n 7, rss 53.4)
windows-arm64 tk-065 open-parejas 285.2 ms (min 277.6, max 287.8, n 7, rss 55.9)
windows-arm64 tk-065 start-agente 439.0 ms (min 435.4, max 442.5, n 7, rss 46.9)
windows-arm64 tk-065 start-main 556.3 ms (min 552.4, max 558.1, n 7, rss 51.5)
windows-arm64 tk-065 start-wizard 480.2 ms (min 469.1, max 481.4, n 7, rss 52.1)
windows-arm64 tk-071 cold-parejas 1833.8 ms (min 1827.1, max 1846.8, n 7, rss 66.5)
windows-arm64 tk-071 open-ajustes 182.8 ms (min 180.1, max 189.3, n 7, rss 67.0)
windows-arm64 tk-071 open-parejas 657.6 ms (min 654.0, max 666.6, n 7, rss 66.5)
windows-arm64 tk-071 start-agente 928.0 ms (min 925.3, max 939.2, n 7, rss 59.9)
windows-arm64 tk-071 start-main 1175.8 ms (min 1169.0, max 1181.1, n 7, rss 61.9)
windows-arm64 tk-071 start-wizard 1079.9 ms (min 1077.0, max 1092.9, n 7, rss 62.7)
windows-arm64 tk-071 switch-pane 171.5 ms (min 170.2, max 202.9, n 7, rss 67.7)
windows-arm64 tk-071-dpi150 cold-parejas 2024.0 ms (min 2017.9, max 2038.1, n 7, rss 67.6)
windows-arm64 tk-071-dpi150 open-ajustes 193.1 ms (min 192.0, max 193.8, n 7, rss 69.2)
windows-arm64 tk-071-dpi150 open-parejas 672.4 ms (min 666.3, max 674.3, n 7, rss 67.6)
windows-arm64 tk-071-dpi150 start-main 1353.0 ms (min 1347.3, max 1363.9, n 7, rss 64.5)
windows-arm64 tk-071-dpi150 switch-pane 181.3 ms (min 180.2, max 181.8, n 7, rss 68.0)
windows-arm64 tk-071-pngcache cold-parejas 1178.8 ms (min 1171.8, max 1186.2, n 7, rss 66.8)
windows-arm64 tk-071-pngcache open-ajustes 131.4 ms (min 130.4, max 142.6, n 7, rss 67.8)
windows-arm64 tk-071-pngcache open-parejas 570.4 ms (min 566.3, max 578.7, n 7, rss 66.8)
windows-arm64 tk-071-pngcache start-agente 376.1 ms (min 371.5, max 381.1, n 7, rss 59.0)
windows-arm64 tk-071-pngcache start-main 605.7 ms (min 599.4, max 610.0, n 7, rss 64.5)
windows-arm64 tk-071-pngcache start-wizard 534.1 ms (min 529.0, max 556.2, n 7, rss 64.1)
windows-arm64 tk-071-pngcache switch-pane 144.9 ms (min 142.8, max 145.2, n 7, rss 66.4)
windows-arm64 tk-bare start-bare 140.1 ms (min 137.8, max 142.4, n 7, rss 32.5)
windows-arm64 tk-flat cold-parejas 318.5 ms (min 308.7, max 334.5, n 7, rss 37.4)
windows-arm64 tk-flat open-parejas 125.6 ms (min 121.3, max 127.8, n 7, rss 39.0)
windows-arm64 tk-flat start-main 250.2 ms (min 243.9, max 252.0, n 7, rss 35.5)
windows-arm64 tk-widgets drawn-150 209.9 ms (min 206.5, max 213.8, n 7, rss 53.9)
windows-arm64 tk-widgets drawn-300 421.7 ms (min 418.1, max 432.4, n 7, rss 55.1)
windows-arm64 tk-widgets drawn-50 91.4 ms (min 89.9, max 91.9, n 7, rss 55.4)
windows-arm64 tk-widgets plain-150 151.3 ms (min 144.3, max 152.5, n 7, rss 34.1)
windows-arm64 tk-widgets plain-300 319.5 ms (min 310.4, max 321.4, n 7, rss 35.3)
windows-arm64 tk-widgets plain-50 62.5 ms (min 59.4, max 65.1, n 7, rss 33.3)
captura windows-arm64 tk-071 main ok=True 515x620 colores=666 printwindow=138 
captura windows-arm64 tk-071 parejas ok=True 966x690 colores=1465 printwindow=220 
captura windows-arm64 tk-071 ajustes ok=True 966x627 colores=1183 printwindow=148 
captura windows-arm64 tk-071 wizard ok=True 885x650 colores=1241 printwindow=100 
captura windows-arm64 tk-071 agente ok=True 494x326 colores=392 printwindow=86 
captura windows-arm64 tk-071-pngcache main ok=True 515x620 colores=666 printwindow=138 
captura windows-arm64 tk-071-pngcache parejas ok=True 966x690 colores=1465 printwindow=220 
captura windows-arm64 tk-071-dpi150 main ok=True 789x635 colores=1150 printwindow=109 
captura windows-arm64 tk-071-dpi150 parejas ok=True 936x635 colores=1001 printwindow=172 
captura windows-arm64 tk-071-dpi150 ajustes ok=True 936x635 colores=1001 printwindow=165 
captura windows-arm64 tk-065 main ok=True 506x567 colores=557 printwindow=126 
captura windows-arm64 tk-065 parejas ok=True 966x608 colores=967 printwindow=171 
captura windows-arm64 tk-065 ajustes ok=True 629x690 colores=811 printwindow=93 
captura windows-arm64 tk-065 wizard ok=True 877x615 colores=1062 printwindow=92 
captura windows-arm64 tk-065 agente ok=True 482x288 colores=380 printwindow=61 
captura windows-arm64 tk-flat main ok=True 537x662 colores=719 printwindow=147 
captura windows-arm64 tk-flat parejas ok=True 1030x710 colores=2198 printwindow=252 
captura windows-arm64 qt-pyside6 main ok=True 533x608 colores=524 printwindow=211 
captura windows-arm64 qt-pyside6 parejas ok=True 1030x692 colores=1810 printwindow=401 
captura windows-arm64 qt-pyside6 ajustes ok=True 978x625 colores=1240 printwindow=271 
```

## linux2

```
linux-x64 qt-pyside6 cold-parejas 278.1 ms (min 276.2, max 282.3, n 7, rss 88.2)
linux-x64 qt-pyside6 open-parejas 31.4 ms (min 30.8, max 31.6, n 7, rss 88.4)
linux-x64 qt-pyside6 start-main 246.9 ms (min 245.4, max 251.6, n 7, rss 80.4)
linux-x64 qt-pyside6 switch-pane 8.6 ms (min 8.5, max 8.7, n 7, rss 84.4)
linux-x64 qt-pyside6 x-start-main-canned 176.1 ms (min 173.3, max 178.5, n 7, rss 68.7)
linux-x64 tk-065 cold-parejas 510.6 ms (min 507.7, max 523.2, n 7, rss 47.2)
linux-x64 tk-065 open-ajustes 69.9 ms (min 67.7, max 71.2, n 7, rss 46.2)
linux-x64 tk-065 open-parejas 72.0 ms (min 70.4, max 78.7, n 7, rss 47.2)
linux-x64 tk-065 start-agente 358.4 ms (min 356.5, max 387.5, n 7, rss 40.6)
linux-x64 tk-065 start-main 438.2 ms (min 434.9, max 443.6, n 7, rss 45.8)
linux-x64 tk-065 start-wizard 394.1 ms (min 390.3, max 419.1, n 7, rss 43.9)
linux-x64 tk-071 cold-parejas 1096.2 ms (min 1084.7, max 1102.3, n 7, rss 59.8)
linux-x64 tk-071 open-ajustes 116.6 ms (min 114.6, max 121.1, n 7, rss 57.9)
linux-x64 tk-071 open-parejas 271.4 ms (min 263.2, max 277.5, n 7, rss 59.8)
linux-x64 tk-071 start-agente 726.9 ms (min 723.9, max 730.5, n 7, rss 52.4)
linux-x64 tk-071 start-main 822.5 ms (min 816.6, max 828.3, n 7, rss 56.5)
linux-x64 tk-071 start-wizard 773.4 ms (min 767.0, max 781.9, n 7, rss 55.8)
linux-x64 tk-071 switch-pane 68.0 ms (min 66.9, max 68.6, n 7, rss 58.7)
linux-x64 tk-071-dpi150 cold-parejas 1352.0 ms (min 1340.9, max 1371.5, n 7, rss 60.8)
linux-x64 tk-071-dpi150 open-ajustes 168.4 ms (min 167.1, max 171.1, n 7, rss 58.9)
linux-x64 tk-071-dpi150 open-parejas 385.1 ms (min 383.7, max 396.1, n 7, rss 60.8)
linux-x64 tk-071-dpi150 start-main 960.6 ms (min 954.7, max 986.8, n 7, rss 57.5)
linux-x64 tk-071-dpi150 switch-pane 98.9 ms (min 98.4, max 100.2, n 7, rss 59.8)
linux-x64 tk-071-pngcache cold-parejas 567.5 ms (min 557.2, max 574.2, n 7, rss 59.6)
linux-x64 tk-071-pngcache open-ajustes 64.9 ms (min 64.4, max 68.5, n 7, rss 58.0)
linux-x64 tk-071-pngcache open-parejas 177.5 ms (min 175.3, max 180.0, n 7, rss 59.6)
linux-x64 tk-071-pngcache start-agente 302.9 ms (min 301.4, max 305.9, n 7, rss 52.0)
linux-x64 tk-071-pngcache start-main 386.5 ms (min 380.9, max 395.9, n 7, rss 56.5)
linux-x64 tk-071-pngcache start-wizard 356.6 ms (min 354.5, max 365.5, n 7, rss 56.1)
linux-x64 tk-071-pngcache switch-pane 40.6 ms (min 40.3, max 44.4, n 7, rss 58.6)
linux-x64 tk-bare start-bare 131.8 ms (min 131.2, max 135.2, n 7, rss 29.4)
linux-x64 tk-flat cold-parejas 210.6 ms (min 207.8, max 216.5, n 7, rss 32.6)
linux-x64 tk-flat open-parejas 60.3 ms (min 59.6, max 66.9, n 7, rss 32.8)
linux-x64 tk-flat start-main 174.1 ms (min 171.8, max 177.1, n 7, rss 31.7)
linux-x64 tk-widgets drawn-150 161.9 ms (min 155.7, max 186.7, n 7, rss 49.4)
linux-x64 tk-widgets drawn-300 337.6 ms (min 311.2, max 354.9, n 7, rss 51.1)
linux-x64 tk-widgets drawn-50 54.6 ms (min 54.2, max 66.8, n 7, rss 48.5)
linux-x64 tk-widgets plain-150 49.3 ms (min 49.0, max 58.7, n 7, rss 31.0)
linux-x64 tk-widgets plain-300 100.6 ms (min 99.4, max 107.8, n 7, rss 32.6)
linux-x64 tk-widgets plain-50 17.5 ms (min 17.0, max 19.7, n 7, rss 29.9)
captura linux-x64 tk-071 main ok=True 571x594 colores=4188 printwindow=- 
captura linux-x64 tk-071 parejas ok=True 1098x965 colores=8638 printwindow=- 
captura linux-x64 tk-071 ajustes ok=True 1014x617 colores=5199 printwindow=- 
captura linux-x64 tk-071 wizard ok=True 919x640 colores=3202 printwindow=- 
captura linux-x64 tk-071 agente ok=True 518x296 colores=2277 printwindow=- 
captura linux-x64 tk-071-pngcache main ok=True 571x594 colores=4188 printwindow=- 
captura linux-x64 tk-071-pngcache parejas ok=True 1098x965 colores=8638 printwindow=- 
captura linux-x64 tk-071-dpi150 main ok=True 787x833 colores=6207 printwindow=- 
captura linux-x64 tk-071-dpi150 parejas ok=True 1533x915 colores=9411 printwindow=- 
captura linux-x64 tk-071-dpi150 ajustes ok=True 1460x886 colores=7286 printwindow=- 
captura linux-x64 tk-065 main ok=True 591x532 colores=4023 printwindow=- 
captura linux-x64 tk-065 parejas ok=True 1212x597 colores=7191 printwindow=- 
captura linux-x64 tk-065 ajustes ok=True 653x839 colores=3018 printwindow=- 
captura linux-x64 tk-065 wizard ok=True 909x600 colores=2964 printwindow=- 
captura linux-x64 tk-065 agente ok=True 498x255 colores=2064 printwindow=- 
captura linux-x64 tk-flat main ok=True 557x656 colores=4753 printwindow=- 
captura linux-x64 tk-flat parejas ok=True 1129x990 colores=10596 printwindow=- 
captura linux-x64 qt-pyside6 main ok=True 531x577 colores=5837 printwindow=- 
captura linux-x64 qt-pyside6 parejas ok=True 1092x930 colores=17311 printwindow=- 
captura linux-x64 qt-pyside6 ajustes ok=True 976x593 colores=8225 printwindow=- 
```

