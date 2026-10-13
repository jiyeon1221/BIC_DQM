//   DAQ  : "BIC" / "JBNU" / "NKFADC"
//   MID  : BIC 41-43, JBNU 21, NKFADC 1-4
//   CH   : BIC/JBNU 0-32, NKFADC 1-4
//   NAME : 채널 이름
//   det, side, sma, z, y : module 위치 정보 (heatmap용)
//     det  : SFIL = 0, Bulk = 1
//     side : -x = 0, +x = 1
//     sma  : SMA flat 번호
//     z    : 빔 방향 (+z), 상류 -> 하류   (SFIL 0-4 = SFIL 4-8, Bulk 0-5 = Bulk 1-6)
//     y    : 아래 -> 위                 (SFIL 0-4, Bulk 0-2)


#ifndef MAPPING_CERN2026_H
#define MAPPING_CERN2026_H

#include <map>
#include <string>
#include <utility>
#include <vector>

struct DQMMapEntry {
	std::string daq;
	int         mid;
	int         ch;
	std::string name;
	int         det;
	int         side;
	int         sma;
	int         z;
	int         y;
};

inline const std::vector<DQMMapEntry>& DQM_MappingTable()
{
	static const std::vector<DQMMapEntry> table = {
		//  DAQ     MID  CH   NAME              det side  sma   z   y
		{"BIC",     41,  1,  "SFIL4_xp_y4",      0,    1,   1,   0,  4 },
		{"BIC",     41,  2,  "SFIL4_xp_y3",      0,    1,   2,   0,  3 },
		{"BIC",     41,  3,  "SFIL4_xp_y2",      0,    1,   3,   0,  2 },
		{"BIC",     41,  4,  "SFIL4_xp_y1",      0,    1,   4,   0,  1 },
		{"BIC",     41,  5,  "SFIL4_xp_y0",      0,    1,   5,   0,  0 },

		{"BIC",     41,  6,  "SFIL5_xp_y4",      0,    1,   6,   1,  4 },
		{"BIC",     41,  7,  "SFIL5_xp_y3",      0,    1,   7,   1,  3 },
		{"BIC",     41,  8,  "SFIL5_xp_y2",      0,    1,   8,   1,  2 },
		{"BIC",     41,  9,  "SFIL5_xp_y1",      0,    1,   9,   1,  1 },
		{"BIC",     41, 10,  "SFIL5_xp_y0",      0,    1,  10,   1,  0 },

		{"BIC",     41, 11,  "SFIL6_xp_y4",      0,    1,  11,   2,  4 },
		{"BIC",     41, 12,  "SFIL6_xp_y3",      0,    1,  12,   2,  3 },
		{"BIC",     41, 13,  "SFIL6_xp_y2",      0,    1,  13,   2,  2 },
		{"BIC",     41, 14,  "SFIL6_xp_y1",      0,    1,  14,   2,  1 },
		{"BIC",     41, 15,  "SFIL6_xp_y0",      0,    1,  15,   2,  0 },

		{"BIC",     41, 16,  "SFIL7_xp_y4",      0,    1,  16,   3,  4 },
		{"BIC",     41, 17,  "SFIL7_xp_y3",      0,    1,  17,   3,  3 },
		{"BIC",     41, 18,  "SFIL7_xp_y2",      0,    1,  18,   3,  2 },
		{"BIC",     41, 19,  "SFIL7_xp_y1",      0,    1,  19,   3,  1 },
		{"BIC",     41, 20,  "SFIL7_xp_y0",      0,    1,  20,   3,  0 },

		{"BIC",     41, 21,  "SFIL8_xp_y4",      0,    1,  21,   4,  4 },
		{"BIC",     41, 22,  "SFIL8_xp_y3",      0,    1,  22,   4,  3 },
		{"BIC",     41, 23,  "SFIL8_xp_y2",      0,    1,  23,   4,  2 },
		{"BIC",     41, 24,  "SFIL8_xp_y1",      0,    1,  24,   4,  1 },
		{"BIC",     41, 25,  "SFIL8_xp_y0",      0,    1,  25,   4,  0 },

		{"BIC",     42,  1,  "SFIL4_xm_y4",      0,    0,  44,   0,  4 },
		{"BIC",     42,  2,  "SFIL4_xm_y3",      0,    0,  45,   0,  3 },
		{"BIC",     42,  3,  "SFIL4_xm_y2",      0,    0,  46,   0,  2 },
		{"BIC",     42,  4,  "SFIL4_xm_y1",      0,    0,  47,   0,  1 },
		{"BIC",     42,  5,  "SFIL4_xm_y0",      0,    0,  48,   0,  0 },

		{"BIC",     42,  6,  "SFIL5_xm_y4",      0,    0,  49,   1,  4 },
		{"BIC",     42,  7,  "SFIL5_xm_y3",      0,    0,  50,   1,  3 },
		{"BIC",     42,  8,  "SFIL5_xm_y2",      0,    0,  51,   1,  2 },
		{"BIC",     42,  9,  "SFIL5_xm_y1",      0,    0,  52,   1,  1 },
		{"BIC",     42, 10,  "SFIL5_xm_y0",      0,    0,  53,   1,  0 },

		{"BIC",     42, 11,  "SFIL6_xm_y4",      0,    0,  54,   2,  4 },
		{"BIC",     42, 12,  "SFIL6_xm_y3",      0,    0,  55,   2,  3 },
		{"BIC",     42, 13,  "SFIL6_xm_y2",      0,    0,  56,   2,  2 },
		{"BIC",     42, 14,  "SFIL6_xm_y1",      0,    0,  57,   2,  1 },
		{"BIC",     42, 15,  "SFIL6_xm_y0",      0,    0,  58,   2,  0 },

		{"BIC",     42, 16,  "SFIL7_xm_y4",      0,    0,  59,   3,  4 },
		{"BIC",     42, 17,  "SFIL7_xm_y3",      0,    0,  60,   3,  3 },
		{"BIC",     42, 18,  "SFIL7_xm_y2",      0,    0,  61,   3,  2 },
		{"BIC",     42, 19,  "SFIL7_xm_y1",      0,    0,  62,   3,  1 },
		{"BIC",     42, 20,  "SFIL7_xm_y0",      0,    0,  63,   3,  0 },

		{"BIC",     42, 21,  "SFIL8_xm_y4",      0,    0,  64,   4,  4 },
		{"BIC",     42, 22,  "SFIL8_xm_y3",      0,    0,  65,   4,  3 },
		{"BIC",     42, 23,  "SFIL8_xm_y2",      0,    0,  66,   4,  2 },
		{"BIC",     42, 24,  "SFIL8_xm_y1",      0,    0,  67,   4,  1 },
		{"BIC",     42, 25,  "SFIL8_xm_y0",      0,    0,  68,   4,  0 },

		{"BIC",     42, 26,  "Bulk5_xm_y2",      1,    0,  81,   4,  2 },
		{"BIC",     42, 27,  "Bulk5_xm_y1",      1,    0,  82,   4,  1 },
		{"BIC",     42, 31,  "Bulk5_xm_y0",      1,    0,  83,   4,  0 },

		{"BIC",     43, 29,  "Bulk6_xm_y2",      1,    0,  84,   5,  2 },
		{"BIC",     43, 31,  "Bulk6_xm_y1",      1,    0,  85,   5,  1 },
		{"BIC",     42, 28,  "Bulk6_xm_y0",      1,    0,  86,   5,  0 },

		{"BIC",     43, 32,  "Bulk1_xp_y2",      1,    1,  26,   0,  2 },
		{"BIC",     43,  2,  "Bulk1_xp_y1",      1,    1,  27,   0,  1 },
		{"BIC",     43,  3,  "Bulk1_xp_y0",      1,    1,  28,   0,  0 },

		{"BIC",     43,  4,  "Bulk2_xp_y2",      1,    1,  29,   1,  2 },
		{"BIC",     43,  5,  "Bulk2_xp_y1",      1,    1,  30,   1,  1 },
		{"BIC",     43,  6,  "Bulk2_xp_y0",      1,    1,  31,   1,  0 },

		{"BIC",     43,  7,  "Bulk3_xp_y2",      1,    1,  32,   2,  2 },
		{"BIC",     43,  8,  "Bulk3_xp_y1",      1,    1,  33,   2,  1 },
		{"BIC",     43,  9,  "Bulk3_xp_y0",      1,    1,  34,   2,  0 },

		{"BIC",     43, 10,  "Bulk4_xp_y2",      1,    1,  35,   3,  2 },
		{"BIC",     43, 11,  "Bulk4_xp_y1",      1,    1,  36,   3,  1 },
		{"BIC",     43, 12,  "Bulk4_xp_y0",      1,    1,  37,   3,  0 },

		{"BIC",     43, 13,  "Bulk5_xp_y2",      1,    1,  38,   4,  2 },
		{"BIC",     43, 14,  "Bulk5_xp_y1",      1,    1,  39,   4,  1 },
		{"BIC",     43, 15,  "Bulk5_xp_y0",      1,    1,  40,   4,  0 },

		{"BIC",     43, 16,  "Bulk6_xp_y2",      1,    1,  41,   5,  2 },
		{"BIC",     43, 17,  "Bulk6_xp_y1",      1,    1,  42,   5,  1 },
		{"BIC",     43, 18,  "Bulk6_xp_y0",      1,    1,  43,   5,  0 },

		{"BIC",     43, 19,  "Bulk1_xm_y2",      1,    0,  69,   0,  2 },
		{"BIC",     43, 20,  "Bulk1_xm_y1",      1,    0,  70,   0,  1 },
		{"BIC",     42, 32,  "Bulk1_xm_y0",      1,    0,  71,   0,  0 },

		{"BIC",     43, 22,  "Bulk2_xm_y2",      1,    0,  72,   1,  2 },
		{"BIC",     43, 23,  "Bulk2_xm_y1",      1,    0,  73,   1,  1 },
		{"BIC",     43, 24,  "Bulk2_xm_y0",      1,    0,  74,   1,  0 },

		{"BIC",     43, 25,  "Bulk3_xm_y2",      1,    0,  75,   2,  2 },
		{"BIC",     42, 30,  "Bulk3_xm_y1",      1,    0,  76,   2,  1 },
		{"BIC",     43, 27,  "Bulk3_xm_y0",      1,    0,  77,   2,  0 },

		{"BIC",     43, 28,  "Bulk4_xm_y2",      1,    0,  78,   3,  2 },
		{"BIC",     42, 29,  "Bulk4_xm_y1",      1,    0,  79,   3,  1 },
		{"BIC",     43, 30,  "Bulk4_xm_y0",      1,    0,  80,   3,  0 },

		{"JBNU",    21,  1,  "HODO_L_01",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  2,  "HODO_L_02",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  3,  "HODO_L_03",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  4,  "HODO_L_04",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  5,  "HODO_L_08",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  6,  "HODO_L_07",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  7,  "HODO_L_06",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  8,  "HODO_L_05",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21,  9,  "HODO_L_12",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 10,  "HODO_L_11",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 11,  "HODO_L_10",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 12,  "HODO_L_09",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 13,  "HODO_L_13",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 14,  "HODO_L_14",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 15,  "HODO_L_15",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 16,  "HODO_L_16",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 17,  "HODO_R_01",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 18,  "HODO_R_02",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 19,  "HODO_R_03",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 20,  "HODO_R_04",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 21,  "HODO_R_08",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 22,  "HODO_R_07",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 23,  "HODO_R_06",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 24,  "HODO_R_05",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 25,  "HODO_R_12",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 26,  "HODO_R_11",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 27,  "HODO_R_10",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 28,  "HODO_R_09",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 29,  "HODO_R_13",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 30,  "HODO_R_14",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 31,  "HODO_R_15",       -1,   -1,  -1,  -1, -1 },
		{"JBNU",    21, 32,  "HODO_R_16",       -1,   -1,  -1,  -1, -1 },

		{"NKFADC",   3,  1,  "DWC1_R",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   3,  2,  "DWC1_L",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   3,  3,  "DWC1_U",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   3,  4,  "DWC1_D",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   4,  1,  "DWC2_R",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   4,  2,  "DWC2_L",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   4,  3,  "DWC2_U",          -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   4,  4,  "DWC2_D",          -1,   -1,  -1,  -1, -1 },

		{"NKFADC",   2,  1,  "CC1",             -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   2,  2,  "CC2",             -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   1,  3,  "TRIG1",           -1,   -1,  -1,  -1, -1 },
		{"NKFADC",   1,  4,  "TRIG2",           -1,   -1,  -1,  -1, -1 },
	};
	return table;
}

inline std::map<std::pair<int, int>, std::vector<int>> GetSimCaloChMap()
{
	std::map<std::pair<int, int>, std::vector<int>> chMap;
	for (const auto& e : DQM_MappingTable())
		if (e.daq == "BIC" && e.det >= 0) chMap[{e.mid, e.ch}] = {e.det, e.side, e.sma, e.z, e.y};
	return chMap;
}

inline std::map<int, std::vector<int>> GetSimGeometryMap()
{
	std::map<int, std::vector<int>> geometryMap;
	for (const auto& entry : GetSimCaloChMap()) geometryMap[entry.second[2]] = entry.second;
	return geometryMap;
}

#endif
