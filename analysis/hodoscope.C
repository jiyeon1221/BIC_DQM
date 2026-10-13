// 사용법: ./hodoscope <RunNo> [nEvt=-1] [plotType=all|o|a|p|i|h] [thr] [-g]   (thr : heatmap 후보 스트립의 intADC 문턱값, 기본 없음)

#include "../include/DQMDraw.h"

#include <TH2F.h>
#include <TProfile.h>

#include <cstdlib>
#include <cstring>

namespace {

bool HodoStrip(const std::string& name, int& side, int& strip)
{
	if (name.size() != 9 || name.compare(0, 5, "HODO_") || (name[5] != 'L' && name[5] != 'R')) return false;
	side  = name[5] == 'L' ? 0 : 1;
	strip = std::atoi(name.c_str() + 7);
	return strip >= 1 && strip <= 16;
}

}

void hodoscope(int RunNo, long long nEvt = -1, const char* plotType = "all", double thr = NAN,
               const char* inPath = kDQMDefaultPath)
{
	const TString type(plotType);
	if (type != "all" && type != "o" && type != "a" && type != "p" && type != "i" && type != "h") {
		std::cerr << "[DQM] plotType must be all, o, a, p, i or h\n";
		return;
	}
	const bool all = type == "all";
	const bool doO = all || type == "o", doA = all || type == "a", doP = all || type == "p";
	const bool doI = all || type == "i", doH = all || type == "h";

	DQMMapping mapping;
	if (!mapping.Load()) return;
	DQMSelection sel;
	if (!sel.Parse("HODO_*", mapping, true)) return;

	const char* sideName[2] = {"L", "R"};
	TH2F*     hO[2][16] = {};
	TProfile* hA[2][16] = {};
	TH1F*     hP[2][16] = {};
	TH1F*     hI[2][16] = {};
	std::map<long long, std::array<double, 32>> evtInt;

	DQM_Loop(sel, inPath, RunNo, 0, nEvt,
	         [&](const DQMKey& k, const ChannelWaveform& w, const DAQInfo& info, long long evt) {
		int side, strip;
		if (!HodoStrip(mapping.Name(k), side, strip)) return;
		const int s = strip - 1;
		const TString id = DQM_ChannelId(mapping, k), label = DQM_ChannelLabel(mapping, k);
		const int nx = info.overlayXBins > 0 ? info.overlayXBins : (int)w.adc.size();

		if (doO && !hO[side][s]) {
			hO[side][s] = new TH2F(Form("hodoscope_%d_overlay_%s", RunNo, id.Data()), label + ";sample;ADC",
			                       nx, 0, nx, info.overlayY.nBins, info.overlayY.min, info.overlayY.max);
			hO[side][s]->SetStats(0);
		}
		if (doA && !hA[side][s]) {
			hA[side][s] = new TProfile(Form("hodoscope_%d_avg_%s", RunNo, id.Data()), label + ";sample;mean ADC",
			                           nx, 0, nx, info.avgY.min, info.avgY.max);
			hA[side][s]->SetStats(0);
			hA[side][s]->SetMinimum(info.adcMin);
			hA[side][s]->SetMaximum(info.adcMax);
		}
		if (doP && !hP[side][s])
			hP[side][s] = new TH1F(Form("hodoscope_%d_peakADC_%s", RunNo, id.Data()), label + ";peak ADC;events",
			                       info.peak.nBins, info.peak.min, info.peak.max);
		if (doI && !hI[side][s])
			hI[side][s] = new TH1F(Form("hodoscope_%d_intADC_%s", RunNo, id.Data()), label + ";integral ADC;events",
			                       info.integral.nBins, info.integral.min, info.integral.max);

		for (int i = 0; i < (int)w.adc.size(); ++i) {
			if (doO) hO[side][s]->Fill(i, w.adc[i]);
			if (doA) hA[side][s]->Fill(i, w.adc[i]);
		}
		const PulseSummary sum = SummarizePulse(w.adc, info);
		if (sum.valid) {
			if (doP) hP[side][s]->Fill(sum.peak);
			if (doI) hI[side][s]->Fill(sum.integral);
		}
		auto it = evtInt.find(evt);
		if (it == evtInt.end()) { it = evtInt.emplace(evt, std::array<double, 32>{}).first; it->second.fill(NAN); }
		if (sum.valid) it->second[side * 16 + s] = sum.integral;
	});
	if (evtInt.empty()) {
		std::cerr << "[DQM] nothing to draw for run " << RunNo << "\n";
		return;
	}
	for (int side = 0; side < 2; ++side)
		for (int s = 0; s < 16; ++s) {
			for (TH1* h : std::initializer_list<TH1*>{hO[side][s], hA[side][s], hP[side][s], hI[side][s]})
				if (h) h->SetDirectory(nullptr);
			if ((doO && !hO[side][s]) || (doA && !hA[side][s]) || (doP && !hP[side][s]) || (doI && !hI[side][s]))
				std::cerr << "[DQM] HODO_" << sideName[side] << Form("_%02d", s + 1) << " : no data\n";
		}

	gStyle->SetOptStat(1111);
	gStyle->SetTitleSize(0.06f, "t");
	std::vector<TCanvas*> canvases;
	auto drawGrid = [&](const char* what, auto hist, const char* opt, bool logY, bool logZ) {
		for (int side = 0; side < 2; ++side) {
			TCanvas* c = new TCanvas(Form("c_hodoscope_%d_%s_%s", RunNo, what, sideName[side]),
			                         Form("Run %d hodoscope %s : %s", RunNo, what, sideName[side]), 1140, 780);
			c->Divide(4, 4, 0.002, 0.002);
			for (int s = 0; s < 16; ++s) {
				TH1* h = hist(side, s);
				if (!h) continue;
				c->cd(s + 1);
				if (logY) gPad->SetLogy();
				if (logZ) gPad->SetLogz();
				h->Draw(opt);
			}
			c->Update();
			canvases.push_back(c);
		}
	};
	if (doO) drawGrid("overlay", [&](int side, int s) -> TH1* { return hO[side][s]; }, "COLZ", false, true);
	if (doA) drawGrid("avg",     [&](int side, int s) -> TH1* { return hA[side][s]; }, "HIST", false, false);
	if (doP) drawGrid("peakADC", [&](int side, int s) -> TH1* { return hP[side][s]; }, "HIST", true, false);
	if (doI) drawGrid("intADC",  [&](int side, int s) -> TH1* { return hI[side][s]; }, "HIST", true, false);

	if (doH) {
		const bool useThr = !std::isnan(thr);
		TH2F* hMap = new TH2F(Form("hodoscope_%d_heatmap", RunNo),
		                      Form("Run %d hodoscope heatmap (max intADC strip%s);L strip;R strip;events", RunNo,
		                           useThr ? Form(", intADC > %g", thr) : ""),
		                      16, 0.5, 16.5, 16, 0.5, 16.5);
		hMap->SetDirectory(nullptr);
		hMap->SetStats(0);
		auto maxStrip = [&](const std::array<double, 32>& v, int side) {
			int best = -1;
			for (int s = 0; s < 16; ++s) {
				const double x = v[side * 16 + s];
				if (std::isnan(x) || (useThr && x <= thr)) continue;
				if (best < 0 || x > v[side * 16 + best]) best = s;
			}
			return best;
		};
		for (const auto& e : evtInt) {
			const int l = maxStrip(e.second, 0), r = maxStrip(e.second, 1);
			if (l >= 0 && r >= 0) hMap->Fill(l + 1, r + 1);
		}
		TCanvas* c = new TCanvas(Form("c_hodoscope_%d_heatmap", RunNo), Form("Run %d hodoscope heatmap", RunNo), 800, 700);
		gPad->SetRightMargin(0.14);
		hMap->Draw("COLZ");
		c->Update();
		canvases.push_back(c);
		std::cout << Form("[DQM] heatmap : %.0f of %zu events filled\n", hMap->GetEntries(), evtInt.size());
	}

	DQM_SaveCanvases(canvases, DQM_OutputPath("Hodoscope", RunNo, Form("hodoscope_%d_%s", RunNo, plotType)));
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(1, "./hodoscope <RunNo> [nEvt=-1] [plotType=all|o|a|p|i|h] [thr=none] [-g]")) return 1;
	const auto& a = app.Args();
	hodoscope(std::stoi(a[0]), a.size() > 1 ? std::stoll(a[1]) : -1, a.size() > 2 ? a[2].c_str() : "all",
	          a.size() > 3 ? std::stod(a[3]) : NAN, DQM_DataPath());
	return app.Run();
}
#endif
