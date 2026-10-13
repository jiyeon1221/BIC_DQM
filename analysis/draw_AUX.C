// 사용법: ./draw_AUX <RunNo> [nEvt=-1] [constantsFile=DWC_calibration_constants.txt] [-g]

#define DWC_CALIBRATION_NO_MAIN
#include "DWC_calibration.C"
#include "../include/DQMDraw.h"

#include <TH2F.h>

void draw_AUX(int RunNo, long long nEvt = -1,
              const char* constantsFile = "DWC_calibration_constants.txt",
              const char* inPath = kDQMDefaultPath)
{
	DWCCalib calib;
	DWC_LoadConstants(constantsFile, calib);
	const char* posUnit = calib.loaded ? "mm" : "uncalibrated";

	TH2F* hXY[2];
	for (int d = 0; d < 2; ++d) {
		hXY[d] = new TH2F(Form("AUX_%d_DWC%d", RunNo, d + 1),
		                  Form("Run %d DWC %d position;X [%s];Y [%s]", RunNo, d + 1, posUnit, posUnit),
		                  200, -100, 100, 200, -100, 100);
		hXY[d]->SetDirectory(nullptr);
		hXY[d]->SetStats(0);
	}
	TH2F* hXcorr = new TH2F(Form("AUX_%d_DWC_X", RunNo),
	                        Form("DWC X corr;DWC 1 X [%s];DWC 2 X [%s]", posUnit, posUnit), 200, -100, 100, 200, -100, 100);
	TH2F* hYcorr = new TH2F(Form("AUX_%d_DWC_Y", RunNo),
	                        Form("DWC Y corr;DWC 1 Y [%s];DWC 2 Y [%s]", posUnit, posUnit), 200, -100, 100, 200, -100, 100);
	for (TH2F* h : {hXcorr, hYcorr}) {
		h->SetDirectory(nullptr);
		h->SetStats(0);
	}

	DWCReader reader[2];
	bool ok[2];
	for (int d = 0; d < 2; ++d) ok[d] = reader[d].Open(inPath, RunNo, 3 + d);
	long long nEvent = 0;
	while ((ok[0] || ok[1]) && (nEvt < 0 || nEvent < nEvt)) {
		double t[2][4];
		bool got[2] = {false, false};
		for (int d = 0; d < 2; ++d) got[d] = ok[d] && reader[d].Next(t[d]);
		if (!got[0] && !got[1]) break;

		double x[2] = {NAN, NAN}, y[2] = {NAN, NAN};
		for (int d = 0; d < 2; ++d) {
			if (!got[d]) continue;
			if (!std::isnan(t[d][0]) && !std::isnan(t[d][1])) x[d] = calib.axis[2 * d].Position(DWC_DeltaLR(t[d]));
			if (!std::isnan(t[d][2]) && !std::isnan(t[d][3])) y[d] = calib.axis[2 * d + 1].Position(DWC_DeltaUD(t[d]));
			if (!std::isnan(x[d]) && !std::isnan(y[d])) hXY[d]->Fill(x[d], y[d]);
		}
		if (!std::isnan(x[0]) && !std::isnan(x[1])) hXcorr->Fill(x[0], x[1]);
		if (!std::isnan(y[0]) && !std::isnan(y[1])) hYcorr->Fill(y[0], y[1]);
		++nEvent;
	}
	for (int d = 0; d < 2; ++d)
		if (ok[d])
			std::cout << Form("[AUX] DWC%d : %lld events read, %lld bad headers\n",
			                  d + 1, reader[d].NRead(), reader[d].NBad());
	if (ok[0] && ok[1] && reader[0].NRead() != reader[1].NRead())
		std::cout << "[AUX] WARNING: MID 3 and MID 4 event counts differ; correlation plots may be misaligned.\n";

	DQMMapping mapping;
	if (!mapping.Load()) return;
	DQMSelection sel;
	if (!sel.Parse("CC1 CC2", mapping)) return;
	std::map<DQMKey, TH1F*> hCC;
	DQM_Loop(sel, inPath, RunNo, 0, nEvt,
	         [&](const DQMKey& k, const ChannelWaveform& w, const DAQInfo& info, long long) {
		TH1F*& h = hCC[k];
		if (!h) {
			h = new TH1F(Form("AUX_%d_%s", RunNo, mapping.Name(k).c_str()),
			             Form("%s;PeakADC;nEvents", mapping.Name(k).c_str()),
			             info.peak.nBins, info.peak.min, info.peak.max);
			h->SetDirectory(nullptr);
			h->SetLineWidth(2);
		}
		const PulseSummary s = SummarizePulse(w.adc, info);
		if (s.valid) h->Fill(s.peak);
	});

	gStyle->SetOptStat(1111);
	TCanvas* c = new TCanvas(Form("c_AUX_%d", RunNo), Form("Run %d AUX", RunNo), 2400, 1300);
	c->Divide(3, 2);
	c->cd(1); gPad->SetRightMargin(0.13); hXY[0]->Draw("colz");
	c->cd(4); gPad->SetRightMargin(0.13); hXY[1]->Draw("colz");
	c->cd(2); gPad->SetRightMargin(0.13); hXcorr->Draw("colz");
	c->cd(5); gPad->SetRightMargin(0.13); hYcorr->Draw("colz");
	const int pad[2] = {3, 6};
	for (size_t i = 0; i < sel.Order().size() && i < 2; ++i) {
		auto it = hCC.find(sel.Order()[i]);
		if (it == hCC.end()) {
			std::cerr << "[AUX] " << DQM_ChannelLabel(mapping, sel.Order()[i]) << " : no data\n";
			continue;
		}
		c->cd(pad[i]);
		gPad->SetLogy();
		it->second->Draw("HIST");
	}
	c->Update();

	DQM_SaveCanvases({c}, DQM_OutputPath("AUX", RunNo, Form("AUX_Run%d", RunNo)));
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(1, "./draw_AUX <RunNo> [nEvt=-1] [constantsFile=DWC_calibration_constants.txt] [-g]")) return 1;
	const auto& a = app.Args();
	draw_AUX(std::stoi(a[0]), a.size() > 1 ? std::stoll(a[1]) : -1,
	         a.size() > 2 ? a[2].c_str() : "DWC_calibration_constants.txt", DQM_DataPath());
	return app.Run();
}
#endif
