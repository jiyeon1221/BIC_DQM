// 사용법: ./draw_avg <RunNo> <nEvt> <channel> [channel ...] [-g]

#include "../include/DQMDraw.h"

#include <TProfile.h>

void draw_avg(int RunNo, const char* channels, long long nEvt = -1,
              const char* inPath = kDQMDefaultPath)
{
	DQM_FillAndDraw<TProfile>(RunNo, channels, 0, nEvt, inPath, "avg", "Avg", "HIST", false, false,
		[](const TString& hname, const TString& label, const ChannelWaveform& w, const DAQInfo& info) {
			const int nx = info.overlayXBins > 0 ? info.overlayXBins : (int)w.adc.size();
			TProfile* h = new TProfile(hname, label + ";sample;mean ADC", nx, 0, nx, info.avgY.min, info.avgY.max);
			h->SetDirectory(nullptr);
			h->SetStats(0);
			h->SetMinimum(info.adcMin);
			h->SetMaximum(info.adcMax);
			return h;
		},
		[](TProfile* h, const ChannelWaveform& w, const DAQInfo&, long long) {
			for (int i = 0; i < (int)w.adc.size(); ++i) h->Fill(i, w.adc[i]);
		});
}

#ifndef __CLING__
#include "../include/DQMApp.h"
int main(int argc, char** argv)
{
	DQMApp app(argc, argv);
	if (!app.Need(3, "./draw_avg <RunNo> <nEvt> <channel> [channel ...] [-g]")) return 1;
	const auto& a = app.Args();
	draw_avg(std::stoi(a[0]), DQM_JoinArgs(a, 2).c_str(), std::stoll(a[1]), DQM_DataPath());
	return app.Run();
}
#endif
