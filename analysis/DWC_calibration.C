// 사용법: ./DWC_calibration <dwc1LU> <dwc1C> <dwc1RD> <dwc2LU> <dwc2C> <dwc2RD> [posMM=30] [nEvt=-1] [-g]

#ifndef DWC_CALIBRATION_C
#define DWC_CALIBRATION_C

#include <TCanvas.h>
#include <TF1.h>
#include <TFile.h>
#include <TGraphErrors.h>
#include <TH1F.h>
#include <TString.h>
#include <TStyle.h>
#include <TSystem.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>


struct DWCAxis {
	double slope  = 1.0;
	double offset = 0.0;
	double Position(double dt) const { return slope * dt + offset; }
};

struct DWCCalib {
	DWCAxis axis[4];
	bool loaded = false;
};

const char* kDWCAxisKey[4] = {"DWC1_X", "DWC1_Y", "DWC2_X", "DWC2_Y"};

bool DWC_LoadConstants(const char* fileName, DWCCalib& c)
{
	c = DWCCalib();
	std::ifstream in(fileName);
	if (!in.is_open()) {
		std::cout << "[DWC] constants file not found: " << fileName
		          << " -> slope=1, offset=0 (positions are NOT calibrated)" << std::endl;
		return false;
	}

	std::string line, key;
	double value = 0.0;
	while (std::getline(in, line)) {
		const std::size_t comment = line.find('#');
		if (comment != std::string::npos) line.erase(comment);
		std::istringstream iss(line);
		if (!(iss >> key >> value)) continue;
		for (int a = 0; a < 4; ++a) {
			if (key == Form("%s_SLOPE",  kDWCAxisKey[a])) c.axis[a].slope  = value;
			if (key == Form("%s_OFFSET", kDWCAxisKey[a])) c.axis[a].offset = value;
		}
	}
	c.loaded = true;
	std::cout << "[DWC] loaded constants from " << fileName << std::endl;
	for (int a = 0; a < 4; ++a)
		std::cout << Form("  %s : slope = %+.5f mm/ns, offset = %+.4f mm\n",
		                  kDWCAxisKey[a], c.axis[a].slope, c.axis[a].offset);
	return true;
}

bool DWC_SaveConstants(const char* fileName, const DWCCalib& c, const TString& note = "")
{
	std::ofstream out(fileName);
	if (!out.is_open()) {
		std::cerr << "[DWC] cannot write " << fileName << std::endl;
		return false;
	}
	out << "# DWC position calibration\n"
	    << "# position_mm = slope_mm_per_ns * delta_t_ns + offset_mm\n";
	if (note.Length()) out << "# " << note << "\n";
	out << std::setprecision(12);
	for (int a = 0; a < 4; ++a) {
		out << kDWCAxisKey[a] << "_SLOPE "  << c.axis[a].slope  << '\n'
		    << kDWCAxisKey[a] << "_OFFSET " << c.axis[a].offset << '\n';
	}
	return true;
}


class DWCReader {
public:
	static constexpr int    nCh       = 4;
	static constexpr int    DLen      = 2048;
	static constexpr int    nADC      = (DLen - 32) / 2;
	static constexpr int    nPed      = 30;
	static constexpr double dtNs      = 2.0;
	static constexpr float  thrFactor = 0.3f;

	bool Open(const char* inPath, int RunNo, int mid)
	{
		fMid  = mid;
		fName = Form("%s/Run_%05d_FADC_%d.dat", inPath, RunNo, mid);
		fIn.open(fName.Data(), std::ios::binary);
		if (!fIn.is_open()) {
			std::cerr << "[DWC] cannot open " << fName << std::endl;
			return false;
		}
		fRaw.assign(DLen * nCh, 0);
		fWF.assign(nADC, 0.f);
		fNRead = fNBad = 0;
		std::cout << "[DWC] opened " << fName << std::endl;
		return true;
	}

	bool Next(double t[nCh])
	{
		for (int ch = 0; ch < nCh; ++ch) t[ch] = NAN;

		fIn.read(reinterpret_cast<char*>(fRaw.data()), fRaw.size());
		if (fIn.gcount() != static_cast<std::streamsize>(fRaw.size())) return false;
		++fNRead;

		for (int ch = 0; ch < nCh; ++ch) {
			unsigned int dlen = 0;
			for (int b = 0; b < 4; ++b) dlen |= (unsigned int)Byte(ch, b) << (8 * b);
			if (dlen != (unsigned int)DLen) {
				if (fNBad++ < 10)
					std::cerr << "[DWC] MID " << fMid << " event " << fNRead - 1 << " ch " << ch
					          << ": unexpected dlen " << dlen << std::endl;
				return true;
			}
		}

		for (int ch = 0; ch < nCh; ++ch) t[ch] = ChannelTime(ch);
		return true;
	}

	long long NRead() const { return fNRead; }
	long long NBad()  const { return fNBad; }

private:
	unsigned char Byte(int ch, int k) const { return fRaw[ch + nCh * k]; }

	double ChannelTime(int ch)
	{
		double ped = 0.0;
		for (int s = 0; s < nADC; ++s) {
			const int idx = 32 + 2 * s;
			const int adc = (Byte(ch, idx) & 0xFF) | ((Byte(ch, idx + 1) & 0x0F) << 8);
			fWF[s] = static_cast<float>(adc);
			if (s < nPed) ped += adc;
		}
		ped /= nPed;
		for (auto& v : fWF) v = static_cast<float>(ped) - v;

		const float maxVal = *std::max_element(fWF.begin(), fWF.end());
		if (maxVal <= 0.f) return NAN;
		const float thr = maxVal * thrFactor;

		for (int s = 1; s < nADC; ++s) {
			if (fWF[s] <= thr) continue;
			const double y0 = fWF[s - 1], y1 = fWF[s];
			const double x0 = (s - 1) * dtNs, x1 = s * dtNs;
			if (y1 == y0) return x1;
			return x0 + (thr - y0) * (x1 - x0) / (y1 - y0);
		}
		return NAN;
	}

	int                        fMid = 0;
	TString                    fName;
	std::ifstream              fIn;
	std::vector<unsigned char> fRaw;
	std::vector<float>         fWF;
	long long                  fNRead = 0, fNBad = 0;
};

const int    kDWCDeltaBins  = 4000;
const double kDWCDeltaRange = 400.0;

inline double DWC_DeltaLR(const double t[4]) { return t[1] - t[0]; }
inline double DWC_DeltaUD(const double t[4]) { return t[2] - t[3]; }


namespace {

bool DWC_FillDeltas(const char* inPath, int RunNo, int mid, long long nEvt, TH1F* hLR, TH1F* hUD)
{
	DWCReader reader;
	if (!reader.Open(inPath, RunNo, mid)) return false;
	double t[4];
	while ((nEvt < 0 || reader.NRead() < nEvt) && reader.Next(t)) {
		if (!std::isnan(t[0]) && !std::isnan(t[1])) hLR->Fill(DWC_DeltaLR(t));
		if (!std::isnan(t[2]) && !std::isnan(t[3])) hUD->Fill(DWC_DeltaUD(t));
	}
	std::cout << Form("[DWC] Run %d MID %d : %lld events read, %lld bad headers\n",
	                  RunNo, mid, reader.NRead(), reader.NBad());
	return true;
}

bool DWC_PeakFit(TH1F* h, double& mean, double& error)
{
	if (h->GetEntries() < 10) {
		std::cerr << "[DWC] too few entries in " << h->GetName() << std::endl;
		return false;
	}
	const double peak = h->GetBinCenter(h->GetMaximumBin());
	const double rms  = h->GetRMS();
	const double half = (rms > 0.2 && rms < 10.0) ? 1.5 * rms : 3.0;
	TF1* g = new TF1(Form("g_%s", h->GetName()), "gaus", peak - half, peak + half);
	g->SetParameters(h->GetMaximum(), peak, rms > 0.0 ? rms : 1.0);
	if (h->Fit(g, "RQ") != 0 || !std::isfinite(g->GetParameter(1))) {
		std::cerr << "[DWC] gaussian fit failed for " << h->GetName() << std::endl;
		return false;
	}
	mean  = g->GetParameter(1);
	error = g->GetParError(1);
	if (!(error > 0.0) || !std::isfinite(error)) error = 1.0;
	return true;
}

} 

void DWC_calibration(
		int dwc1LU, int dwc1C, int dwc1RD,
		int dwc2LU, int dwc2C, int dwc2RD,
		double posMM = 30.0,
		long long nEvt = -1,
		const char* inPath = "/home/kobic/26CERNData/binary",
		const char* constantsFile = "DWC_calibration_constants.txt",
		const char* fitFile = "DWC_calibration_fits.root")
{
	gStyle->SetOptFit(1);

	const int    runs[2][3]   = {{dwc1LU, dwc1C, dwc1RD}, {dwc2LU, dwc2C, dwc2RD}};
	const char*  ptName[3]    = {"LU", "C", "RD"};
	const double position[3]  = {-posMM, 0.0, posMM};

	TFile* fout = TFile::Open(fitFile, "RECREATE");
	if (!fout || fout->IsZombie()) {
		std::cerr << "[DWC] cannot create " << fitFile << std::endl;
		return;
	}

	double dt[4][3] = {{0}}, dtErr[4][3] = {{0}};
	TH1F*  hDelta[4][3] = {{nullptr}};

	TCanvas* cDelta = new TCanvas("cDWCCalibDelta", "DWC calibration #Deltat", 1500, 1000);
	cDelta->Divide(3, 4);

	for (int chamber = 0; chamber < 2; ++chamber) {
		const int mid = 3 + chamber;
		for (int p = 0; p < 3; ++p) {
			const int run = runs[chamber][p];
			TH1F* hLR = new TH1F(Form("h_DWC%d_LR_%s_Run%d", chamber + 1, ptName[p], run),
			                     Form("DWC%d L-R, %s (Run %d);#Deltat_{LR} [ns];Events", chamber + 1, ptName[p], run),
			                     kDWCDeltaBins, -kDWCDeltaRange, kDWCDeltaRange);
			TH1F* hUD = new TH1F(Form("h_DWC%d_UD_%s_Run%d", chamber + 1, ptName[p], run),
			                     Form("DWC%d U-D, %s (Run %d);#Deltat_{UD} [ns];Events", chamber + 1, ptName[p], run),
			                     kDWCDeltaBins, -kDWCDeltaRange, kDWCDeltaRange);
			hLR->SetDirectory(nullptr);
			hUD->SetDirectory(nullptr);
			hDelta[2 * chamber][p]     = hLR;
			hDelta[2 * chamber + 1][p] = hUD;

			if (!DWC_FillDeltas(inPath, run, mid, nEvt, hLR, hUD)) { fout->Close(); return; }
			for (int local = 0; local < 2; ++local) {
				const int a = 2 * chamber + local;
				if (!DWC_PeakFit(hDelta[a][p], dt[a][p], dtErr[a][p])) { fout->Close(); return; }
			}
		}
	}

	for (int a = 0; a < 4; ++a)
		for (int p = 0; p < 3; ++p) {
			cDelta->cd(a * 3 + p + 1);
			hDelta[a][p]->Draw();
		}
	cDelta->Update();

	DWCCalib calib;
	TCanvas* cFit = new TCanvas("cDWCCalibFit", "DWC calibration fits", 1200, 900);
	cFit->Divide(2, 2);
	const char* axisTitle[4] = {
		"DWC1 X;#Deltat_{LR} [ns];x [mm]", "DWC1 Y;#Deltat_{UD} [ns];y [mm]",
		"DWC2 X;#Deltat_{LR} [ns];x [mm]", "DWC2 Y;#Deltat_{UD} [ns];y [mm]"};

	for (int a = 0; a < 4; ++a) {
		double posErr[3] = {0, 0, 0};
		TGraphErrors* g = new TGraphErrors(3, dt[a], position, dtErr[a], posErr);
		g->SetName(Form("g_%s", kDWCAxisKey[a]));
		g->SetTitle(axisTitle[a]);
		g->SetMarkerStyle(20);
		TF1* line = new TF1(Form("fit_%s", kDWCAxisKey[a]), "pol1");
		if (g->Fit(line, "Q") != 0) {
			std::cerr << "[DWC] linear fit failed for " << kDWCAxisKey[a] << std::endl;
			fout->Close();
			return;
		}
		calib.axis[a].offset = line->GetParameter(0);
		calib.axis[a].slope  = line->GetParameter(1);

		cFit->cd(a + 1);
		g->Draw("AP");
		fout->cd();
		g->Write();
	}
	cFit->Update();

	fout->cd();
	for (int a = 0; a < 4; ++a)
		for (int p = 0; p < 3; ++p) hDelta[a][p]->Write();
	cDelta->Write();
	cFit->Write();
	fout->Close();

	std::cout << "\n[DWC] calibration result (pos = +-" << posMM << " mm)\n";
	for (int a = 0; a < 4; ++a)
		std::cout << Form("  %s : dt = (%+.3f, %+.3f, %+.3f) ns -> slope = %+.5f mm/ns, offset = %+.4f mm\n",
		                  kDWCAxisKey[a], dt[a][0], dt[a][1], dt[a][2],
		                  calib.axis[a].slope, calib.axis[a].offset);

	const TString note = Form("runs DWC1 %d/%d/%d, DWC2 %d/%d/%d, pos = +-%g mm",
	                          dwc1LU, dwc1C, dwc1RD, dwc2LU, dwc2C, dwc2RD, posMM);
	if (DWC_SaveConstants(constantsFile, calib, note))
		std::cout << "[DWC] wrote " << constantsFile << " and " << fitFile << std::endl;
}

#if !defined(__CLING__) && !defined(DWC_CALIBRATION_NO_MAIN)
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(6, "./DWC_calibration <dwc1LU> <dwc1C> <dwc1RD> <dwc2LU> <dwc2C> <dwc2RD> [posMM=30] [nEvt=-1] [-g]"))
		return 1;
	const auto& a = app.Args();
	DWC_calibration(std::stoi(a[0]), std::stoi(a[1]), std::stoi(a[2]), std::stoi(a[3]), std::stoi(a[4]), std::stoi(a[5]),
	                a.size() > 6 ? std::stod(a[6]) : 30.0, a.size() > 7 ? std::stoll(a[7]) : -1, DQM_DataPath());
	return app.Run();
}
#endif

#endif 
