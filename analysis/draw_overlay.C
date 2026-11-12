// 사용법: ./draw_overlay <RunNo> <nEvt> <channel> [channel ...] [-g]

#include "../include/DQMDraw.h"

#include <TH2F.h>

void draw_overlay(int RunNo, const char* channels, long long nEvt = -1,
                  const char* inPath = kDQMDefaultPath)
{
	std::map<TH2F*, double> maxima;
	DQM_FillAndDraw<TH2F>(RunNo, channels, 0, nEvt, inPath, "overlay", "Overlay", "COLZ", false, true,
		[](const TString& hname, const TString& label, const ChannelWaveform& w, const DAQInfo& info) {
			const int nx = info.overlayXBins > 0 ? info.overlayXBins : (int)w.adc.size();
			TH2F* h = new TH2F(hname, label + ";sample;ADC", nx, 0, nx,
			                   info.overlayY.nBins, info.overlayY.min, info.overlayY.max);
			h->SetDirectory(nullptr);
			h->SetStats(0);
			if (std::string(info.name) == "BIC") h->SetCanExtend(TH1::kYaxis);
			return h;
		},
		[&](TH2F* h, const ChannelWaveform& w, const DAQInfo& info, long long) {
			for (int i = 0; i < (int)w.adc.size(); ++i) h->Fill(i, w.adc[i]);
			if (std::string(info.name) == "BIC" && !w.adc.empty())
				maxima[h] = std::max(maxima[h], *std::max_element(w.adc.begin(), w.adc.end()));
		},
		[&](TH2F* h, const DQMKey& key) {
			if (std::get<0>(key) != "BIC") return;
			const auto range = DQM_ADCDisplayRange(BICReader().Info(), maxima[h]);
			h->ExtendAxis(range[1], h->GetYaxis());
			h->GetYaxis()->SetRangeUser(range[0], range[1]);
		});
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(3, "./draw_overlay <RunNo> <nEvt> <channel> [channel ...] [-g]")) return 1;
	const auto& a = app.Args();
	draw_overlay(std::stoi(a[0]), DQM_JoinArgs(a, 2).c_str(), std::stoll(a[1]), DQM_DataPath());
	return app.Run();
}
#endif
