// 사용법: ./DWC <RunNo> [nEvt=-1] [constantsFile=DWC_calibration_constants.txt] [-g]


#define DWC_CALIBRATION_NO_MAIN
#include "DWC_calibration.C"
#include "../include/DQMSave.h"

#include <TH2F.h>

void DWC(
		int RunNo,
		long long nEvt = -1,
		const char* inPath = "/home/kobic/26CERNData/binary",
		const char* constantsFile = "DWC_calibration_constants.txt",
		const char* outDir = "dwc")
{
	gStyle->SetOptStat(1111);
	gStyle->SetTitleSize(0.04f);

	DWCCalib calib;
	DWC_LoadConstants(constantsFile, calib);
	const char* posUnit = calib.loaded ? "mm" : "uncalibrated";

	const char* chName[4] = {"R", "L", "U", "D"};
	const double tMax = DWCReader::nADC * DWCReader::dtNs;

	TH1F* hTime[2][4];
	TH1F* hLR[2];
	TH1F* hUD[2];
	TH1F* hX[2];
	TH1F* hY[2];
	TH2F* hXY[2];

	for (int d = 0; d < 2; ++d) {
		const int n = d + 1;
		for (int ch = 0; ch < 4; ++ch) {
			hTime[d][ch] = new TH1F(Form("h_time_DWC%d_%s", n, chName[ch]),
			                        Form("DWC%d %s time;t [ns];Events", n, chName[ch]),
			                        DWCReader::nADC, 0, tMax);
		}
		hLR[d] = new TH1F(Form("h_deltaDWC%d_LR", n), Form("DWC%d L-R;#Deltat_{LR} [ns];Events", n),
		                  kDWCDeltaBins, -kDWCDeltaRange, kDWCDeltaRange);
		hUD[d] = new TH1F(Form("h_deltaDWC%d_UD", n), Form("DWC%d U-D;#Deltat_{UD} [ns];Events", n),
		                  kDWCDeltaBins, -kDWCDeltaRange, kDWCDeltaRange);
		hX[d]  = new TH1F(Form("h_xDWC%d", n), Form("DWC%d x;x [%s];Events", n, posUnit), 400, -100, 100);
		hY[d]  = new TH1F(Form("h_yDWC%d", n), Form("DWC%d y;y [%s];Events", n, posUnit), 400, -100, 100);
		hXY[d] = new TH2F(Form("h_xyDWC%d", n), Form("DWC%d y vs x;x [%s];y [%s]", n, posUnit, posUnit),
		                  200, -100, 100, 200, -100, 100);
	}
	TH2F* hXcorr = new TH2F("h_xDWC1_vs_xDWC2", Form("DWC x correlation;DWC1 x [%s];DWC2 x [%s]", posUnit, posUnit),
	                        200, -100, 100, 200, -100, 100);
	TH2F* hYcorr = new TH2F("h_yDWC1_vs_yDWC2", Form("DWC y correlation;DWC1 y [%s];DWC2 y [%s]", posUnit, posUnit),
	                        200, -100, 100, 200, -100, 100);

	DWCReader reader[2];
	bool ok[2];
	for (int d = 0; d < 2; ++d) ok[d] = reader[d].Open(inPath, RunNo, 3 + d);
	if (!ok[0] && !ok[1]) return;

	long long nEvent = 0;
	while (nEvt < 0 || nEvent < nEvt) {
		double t[2][4];
		bool got[2] = {false, false};
		for (int d = 0; d < 2; ++d) got[d] = ok[d] && reader[d].Next(t[d]);
		if (!got[0] && !got[1]) break;

		double x[2] = {NAN, NAN}, y[2] = {NAN, NAN};
		for (int d = 0; d < 2; ++d) {
			if (!got[d]) continue;
			for (int ch = 0; ch < 4; ++ch)
				if (!std::isnan(t[d][ch])) hTime[d][ch]->Fill(t[d][ch]);

			if (!std::isnan(t[d][0]) && !std::isnan(t[d][1])) {
				const double dLR = DWC_DeltaLR(t[d]);
				hLR[d]->Fill(dLR);
				x[d] = calib.axis[2 * d].Position(dLR);
				hX[d]->Fill(x[d]);
			}
			if (!std::isnan(t[d][2]) && !std::isnan(t[d][3])) {
				const double dUD = DWC_DeltaUD(t[d]);
				hUD[d]->Fill(dUD);
				y[d] = calib.axis[2 * d + 1].Position(dUD);
				hY[d]->Fill(y[d]);
			}
			if (!std::isnan(x[d]) && !std::isnan(y[d])) hXY[d]->Fill(x[d], y[d]);
		}
		if (!std::isnan(x[0]) && !std::isnan(x[1])) hXcorr->Fill(x[0], x[1]);
		if (!std::isnan(y[0]) && !std::isnan(y[1])) hYcorr->Fill(y[0], y[1]);
		++nEvent;
	}
	for (int d = 0; d < 2; ++d)
		if (ok[d])
			std::cout << Form("[DWC] DWC%d : %lld events read, %lld bad headers\n",
			                  d + 1, reader[d].NRead(), reader[d].NBad());
	if (ok[0] && ok[1] && reader[0].NRead() != reader[1].NRead())
		std::cout << "[DWC] WARNING: MID 3 and MID 4 event counts differ; correlation plots may be misaligned.\n";

	TCanvas* cTime = new TCanvas(Form("cDWCTime_Run%d", RunNo), Form("Run %d DWC channel time", RunNo), 1600, 800);
	cTime->Divide(4, 2);
	for (int d = 0; d < 2; ++d)
		for (int ch = 0; ch < 4; ++ch) {
			cTime->cd(d * 4 + ch + 1);
			hTime[d][ch]->Draw();
		}

	TCanvas* cDelta = new TCanvas(Form("cDWCDelta_Run%d", RunNo), Form("Run %d DWC #Deltat", RunNo), 1200, 900);
	cDelta->Divide(2, 2);
	for (int d = 0; d < 2; ++d) {
		cDelta->cd(d * 2 + 1); hLR[d]->Draw();
		cDelta->cd(d * 2 + 2); hUD[d]->Draw();
	}

	TCanvas* cPos = new TCanvas(Form("cDWCPos_Run%d", RunNo), Form("Run %d DWC position", RunNo), 1500, 900);
	cPos->Divide(3, 2);
	for (int d = 0; d < 2; ++d) {
		cPos->cd(d * 3 + 1); hX[d]->Draw();
		cPos->cd(d * 3 + 2); hY[d]->Draw();
		cPos->cd(d * 3 + 3); hXY[d]->Draw("COLZ");
	}

	TCanvas* cCorr = new TCanvas(Form("cDWCCorr_Run%d", RunNo), Form("Run %d DWC1 vs DWC2", RunNo), 1200, 550);
	cCorr->Divide(2, 1);
	cCorr->cd(1); hXcorr->Draw("COLZ");
	cCorr->cd(2); hYcorr->Draw("COLZ");

	for (TCanvas* c : {cTime, cDelta, cPos, cCorr}) c->Update();

	const TString outName = DQM_OutputPath(outDir, RunNo, Form("DWC_Run%d", RunNo));
	TFile* fout = TFile::Open(outName, "RECREATE");
	if (fout && !fout->IsZombie()) {
		for (int d = 0; d < 2; ++d) {
			for (int ch = 0; ch < 4; ++ch) hTime[d][ch]->Write();
			hLR[d]->Write(); hUD[d]->Write();
			hX[d]->Write();  hY[d]->Write(); hXY[d]->Write();
		}
		hXcorr->Write(); hYcorr->Write();
		for (TCanvas* c : {cTime, cDelta, cPos, cCorr}) c->Write();
		fout->Close();
		std::cout << "[DWC] wrote " << outName << std::endl;
	}
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(1, "./DWC <RunNo> [nEvt=-1] [constantsFile=DWC_calibration_constants.txt] [-g]")) return 1;
	const auto& a = app.Args();
	DWC(std::stoi(a[0]), a.size() > 1 ? std::stoll(a[1]) : -1, DQM_DataPath(),
	         a.size() > 2 ? a[2].c_str() : "DWC_calibration_constants.txt");
	return app.Run();
}
#endif
