#ifndef DQM_PROGRESS_H
#define DQM_PROGRESS_H

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#include <unistd.h>

class DQMProgress {
public:
	DQMProgress(const std::string& label, long long total, const char* unit = "events")
		: fLabel(label), fUnit(unit), fTotal(total), fTerminal(isatty(STDOUT_FILENO)),
		  fStart(Clock::now()), fLast(fStart)
	{
		Print(false, "");
	}

	~DQMProgress() { if (!fFinished) Finish("stopped"); }

	void Update(long long current)
	{
		fCurrent = current;
		const auto now = Clock::now();
		if (std::chrono::duration<double>(now - fLast).count() < (fTerminal ? 0.25 : 2.0)) return;
		Print(false, "");
	}

	void Finish(const char* status = "done")
	{
		if (fFinished) return;
		Print(true, status);
		fFinished = true;
	}

private:
	using Clock = std::chrono::steady_clock;

	static std::string Duration(double seconds)
	{
		const long long s = static_cast<long long>(std::max(0., seconds));
		std::ostringstream out;
		out << std::setfill('0') << std::setw(2) << s / 3600 << ':'
		    << std::setw(2) << s / 60 % 60 << ':' << std::setw(2) << s % 60;
		return out.str();
	}

	void Print(bool final, const char* status)
	{
		fLast = Clock::now();
		const double elapsed = std::chrono::duration<double>(fLast - fStart).count();
		const double rate = elapsed > 0. ? fCurrent / elapsed : 0.;
		std::ostringstream out;
		out << "[DQM] " << fLabel << ' ';
		if (fTotal >= 0) {
			const double fraction = fTotal > 0 ? std::min(1., double(fCurrent) / fTotal) : (final ? 1. : 0.);
			const int filled = static_cast<int>(fraction * 24);
			out << '[' << std::string(filled, '=') << std::string(24 - filled, ' ') << "] "
			    << std::fixed << std::setprecision(1) << 100. * fraction << "% "
			    << fCurrent << '/' << fTotal;
		} else {
			out << fCurrent << "/?";
		}
		out << ' ' << fUnit << " | elapsed " << Duration(elapsed);
		if (rate > 0.) {
			if (fUnit == "bytes") out << " | " << std::fixed << std::setprecision(1) << rate / 1048576. << " MiB/s";
			else out << " | " << std::fixed << std::setprecision(0) << rate << ' ' << fUnit << "/s";
			if (!final && fTotal >= fCurrent) out << " | ETA " << Duration((fTotal - fCurrent) / rate);
		}
		if (final) out << " | " << status;
		const std::string line = out.str();
		if (fTerminal) {
			std::cout << '\r' << line;
			if (fLastWidth > line.size()) std::cout << std::string(fLastWidth - line.size(), ' ');
			fLastWidth = line.size();
		} else std::cout << line;
		if (!fTerminal || final) std::cout << '\n';
		std::cout << std::flush;
	}

	std::string fLabel, fUnit;
	long long fTotal, fCurrent = 0;
	bool fTerminal, fFinished = false;
	size_t fLastWidth = 0;
	Clock::time_point fStart, fLast;
};

#endif
