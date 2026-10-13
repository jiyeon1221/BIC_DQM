// 사용법: ./draw_heatmap <RunNo> [nEvt] [var] [-g]


#include "../include/DQMDraw.h"

#include <TH2F.h>

#include <cstring>

void draw_heatmap(int RunNo, long long nEvt = -1, const char* var = "int",
                 const char* inPath = kDQMDefaultPath)
{
	const bool usePeak = !std::strcmp(var, "peak");
	if (!usePeak && std::strcmp(var, "int")) {
		std::cerr << "[DQM] var must be \"int\" or \"peak\"\n";
		return;
	}

	DQMMapping mapping;
	if (!mapping.Load()) return;
	DQMSelection sel;
	if (!sel.Parse("SFIL* Bulk*", mapping, true)) return;
	const auto geo = GetSimCaloChMap();

	std::map<DQMKey, std::pair<double, double>> acc;
	DQM_Loop(sel, inPath, RunNo, 0, nEvt,
	         [&](const DQMKey& k, const ChannelWaveform& w, const DAQInfo& info, long long) {
		const PulseSummary s = SummarizePulse(w.adc, info);
		if (!s.valid) return;
		auto& a = acc[k];
		a.first  += usePeak ? s.peak : s.integral;
		a.second += 1;
	});
	if (acc.empty()) {
		std::cerr << "[DQM] nothing to draw for run " << RunNo << "\n";
		return;
	}

	const char* detName[2]  = {"SFIL", "Bulk"};
	const char* sideId[2]   = {"xm", "xp"};
	const char* sideName[2] = {"-x", "+x"};
	const int   nZ[2] = {5, 6}, nY[2] = {5, 3}, firstModule[2] = {4, 1};
	const char* what = usePeak ? "mean peak ADC" : "mean int ADC";
	TH2F* h[2][2];
	for (int det = 0; det < 2; ++det) {
		for (int side = 0; side < 2; ++side) {
			h[det][side] = new TH2F(Form("heatmap_%d_%s_%s_%s", RunNo, var, detName[det], sideId[side]),
			                        Form("Run %d %s %s : %s;module;y", RunNo, detName[det], sideName[side], what),
			                        nZ[det], 0, nZ[det], nY[det], 0, nY[det]);
			h[det][side]->SetDirectory(nullptr);
			h[det][side]->SetStats(0);
			h[det][side]->SetMarkerSize(1.6);
			for (int z = 0; z < nZ[det]; ++z)
				h[det][side]->GetXaxis()->SetBinLabel(z + 1, Form("%s%d", detName[det], z + firstModule[det]));
			for (int y = 0; y < nY[det]; ++y)
				h[det][side]->GetYaxis()->SetBinLabel(y + 1, Form("y%d", y));
		}
	}

	for (const auto& k : sel.Order()) {
		auto a = acc.find(k);
		if (a == acc.end()) {
			std::cerr << "[DQM] " << DQM_ChannelLabel(mapping, k) << " : no data (file missing or no event in range)\n";
			continue;
		}
		const auto g = geo.find({std::get<1>(k), std::get<2>(k)});
		if (g == geo.end()) continue;
		const int det = g->second[0], side = g->second[1], z = g->second[3], y = g->second[4];
		if (det < 0 || det > 1 || side < 0 || side > 1) continue;
		h[det][side]->Fill(z + 0.5, y + 0.5, a->second.first / a->second.second);
	}

	gStyle->SetPaintTextFormat(".0f");
	TCanvas* c = new TCanvas(Form("c_heatmap_%d_%s", RunNo, var), Form("Run %d heatmap (%s)", RunNo, what), 1200, 900);
	c->Divide(2, 2);
	for (int det = 0; det < 2; ++det) {
		for (int side = 0; side < 2; ++side) {
			c->cd(det * 2 + side + 1);
			gPad->SetRightMargin(0.15);
			h[det][side]->Draw("COLZ TEXT");
		}
	}
	c->Update();

	DQM_SaveCanvases({c}, DQM_OutputPath("Heatmap", RunNo, Form("heatmap_%d_%s", RunNo, var)));
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(1, "./draw_heatmap <RunNo> [nEvt=-1] [var=int|peak] [-g]")) return 1;
	const auto& a = app.Args();
	draw_heatmap(std::stoi(a[0]), a.size() > 1 ? std::stoll(a[1]) : -1, a.size() > 2 ? a[2].c_str() : "int",
	            DQM_DataPath());
	return app.Run();
}
#endif
