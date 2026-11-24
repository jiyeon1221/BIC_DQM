#pragma once
// Calculate ADC metrics and calibrated DWC/HODO values from raw waveforms.
#include <vector>
#include <algorithm>
#include <cmath>
#include <limits>

namespace DQMLive {
struct Features {
    std::vector<short> adc, toa, tot;
    std::vector<int> offsets;
    std::vector<unsigned char> present, usable;
    std::vector<double> baseline, peak, integral, timestamps, derived;
    std::vector<unsigned long long> triggers;
    std::vector<int> daqs, dwc, hodoSide, hodoStrip;
    std::vector<double> calibration;

    void configure(const std::vector<int>& q, const std::vector<int>& d,
                   const std::vector<double>& c, const std::vector<int>& hs,
                   const std::vector<int>& ht) {
        daqs = q;
        dwc = d;
        calibration = c;
        hodoSide = hs;
        hodoStrip = ht;
    }

    // Calculate the NKFADC 30% leading-edge time at 2 ns per sample.
    double arrival(int i) const {
        const double nan = std::numeric_limits<double>::quiet_NaN();
        if (i < 0 || !present[i] || offsets[i + 1] - offsets[i] < 31)
            return nan;
        int a = offsets[i], b = offsets[i + 1];
        double base = 0, maximum = 0;
        for (int j = a; j < a + 30; ++j)
            base += adc[j];
        base /= 30.;
        for (int j = a; j < b; ++j)
            maximum = std::max(maximum, base - adc[j]);
        if (maximum <= 0)
            return nan;
        for (int j = a + 1; j < b; ++j)
            if (base - adc[j] > .3 * maximum) {
                double y0 = base - adc[j - 1], y1 = base - adc[j];
                return y1 == y0 ? 2. * (j - a)
                                : 2. * (j - a - 1) + 2. * (.3 * maximum - y0) / (y1 - y0);
            }
        return nan;
    }

    // Calculate DAQ-specific baselines, peaks, integrals, and calibrated positions.
    void setRaw(const short* a, int na, const int* o, int nc, const unsigned char* p,
                const double* ts, const unsigned long long* tr) {
        const double nan = std::numeric_limits<double>::quiet_NaN();
        adc.assign(a, a + na);
        offsets.assign(o, o + nc + 1);
        present.assign(p, p + nc);
        timestamps.assign(ts, ts + nc);
        triggers.assign(tr, tr + nc);
        usable.assign(nc, 0);
        baseline.assign(nc, nan);
        peak.assign(nc, nan);
        integral.assign(nc, nan);
        derived.assign(6, nan);
        for (int i = 0; i < nc; ++i) {
            if (!p[i])
                continue;
            if (daqs[i] < 2)
                baseline[i] = 0;
            int begin = o[i], end = o[i + 1], n = end - begin, first = begin, last = end;
            double base = 0;
            if (!n)
                continue;
            if (daqs[i] == 3) { // GCROC: ignore sample zero, baseline samples 1..4
                if (n < 20 || n > 40)
                    continue;
                for (int j = begin + 1; j < begin + 5; ++j)
                    base += adc[j] / 4.;
                first = begin + 1;
            } else if (daqs[i] == 2) {
                for (int j = begin; j < begin + std::min(n, 30); ++j)
                    base += adc[j];
                base /= std::min(n, 30);
            } else if (daqs[i] == 0) {
                bool nonzero = false;
                for (int j = begin; j < end; ++j)
                    nonzero |= adc[j] != 0;
                if (!nonzero || n <= 10)
                    continue;
                first = begin + 10;
                last = std::min(end, begin + 60);
            } else
                last = std::min(end, begin + 240);
            double pk = daqs[i] == 2 ? 0 : -std::numeric_limits<double>::infinity(), sum = 0;
            for (int j = first; j < last; ++j) {
                double signal = daqs[i] == 2 ? base - adc[j] : adc[j] - base;
                pk = std::max(pk, signal);
                sum += signal;
            }
            usable[i] = 1;
            baseline[i] = base;
            peak[i] = pk;
            integral[i] = sum;
        }
        for (int ax = 0; ax < 4; ++ax)
            derived[ax] = calibration[2 * ax] * (arrival(dwc[2 * ax]) - arrival(dwc[2 * ax + 1])) +
                calibration[2 * ax + 1];
        double maximum[2] = {-std::numeric_limits<double>::infinity(),
                             -std::numeric_limits<double>::infinity()};
        for (int i = 0; i < nc; ++i) {
            int side = hodoSide[i];
            if (side < 0 || !usable[i])
                continue;
            if (integral[i] > maximum[side] ||
                (integral[i] == maximum[side] && hodoStrip[i] > derived[4 + side])) {
                maximum[side] = integral[i];
                derived[4 + side] = hodoStrip[i];
            }
        }
    }

    void setTiming(const short* a, const short* b, int n) {
        toa.assign(a, a + n);
        tot.assign(b, b + n);
    }
};
}
