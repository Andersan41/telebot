import { useState, useMemo } from "react";
import {
  ComposedChart,
  LineChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ---------------------------------------------------------------------------
// Демо-данные. В реальном проекте эти массивы приходят с бэкенда/WS-стрима
// биржи: сумма открытых позиций (Open Interest) и ставка финансирования
// (Funding Rate). Форма объектов ниже — то, что обычно отдаёт REST/WS API.
// ---------------------------------------------------------------------------

function genOpenInterest() {
  const points = [];
  let oi = 373.76;
  const labels = ["21:40", "22:20", "23:00", "23:35", "00:15"];
  for (let i = 0; i < 40; i++) {
    oi -= Math.random() * 0.25 + (i < 15 ? 0.15 : 0);
    oi = Math.max(oi, 367.2);
    points.push({
      time:
        i % 8 === 0 && labels[i / 8]
          ? labels[i / 8]
          : "",
      oi: Number(oi.toFixed(2)),
      volume: Number((Math.random() * 4).toFixed(2)),
    });
  }
  return points;
}

function genFunding() {
  const points = [];
  const labels = ["08-15", "08-22", "08-29", "09-05", "09-11"];
  for (let i = 0; i < 60; i++) {
    const dip = Math.random() < 0.12;
    const value = dip
      ? -(Math.random() * 0.06 + 0.01)
      : Math.random() * 0.01;
    points.push({
      date: i % 12 === 0 && labels[i / 12] ? labels[i / 12] : "",
      rate: Number(value.toFixed(4)),
    });
  }
  return points;
}

const RANGES = ["5 мин", "15 мин", "30 мин", "1 ч", "12 ч", "1 д"];
const TABS = ["Торговые данные", "Тренд торговли"];

export default function ExchangeDashboard() {
  const [activeTab, setActiveTab] = useState(0);
  const [range, setRange] = useState(0);

  const oiData = useMemo(() => genOpenInterest(), [range]);
  const fundingData = useMemo(() => genFunding(), []);

  return (
    <div
      style={{
        background: "#0B0E11",
        color: "#EAECEF",
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        padding: "20px 24px",
        borderRadius: 8,
        minHeight: 480,
      }}
    >
      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            style={{
              background: activeTab === i ? "rgba(240,185,11,0.12)" : "transparent",
              color: activeTab === i ? "#F0B90B" : "#848E9C",
              border: "none",
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 32,
        }}
      >
        {/* ---------------- Open Interest ---------------- */}
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, margin: "0 0 12px" }}>
            Сумма открытых позиций
          </h3>

          <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
            {RANGES.map((r, i) => (
              <button
                key={r}
                onClick={() => setRange(i)}
                style={{
                  background: range === i ? "#F0B90B" : "#181A20",
                  color: range === i ? "#0B0E11" : "#848E9C",
                  border: "none",
                  borderRadius: 4,
                  padding: "4px 10px",
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                {r}
              </button>
            ))}
          </div>

          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={oiData} margin={{ left: 0, right: 8 }}>
              <CartesianGrid
                stroke="#1E2329"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="time"
                tick={{ fill: "#848E9C", fontSize: 11 }}
                axisLine={{ stroke: "#1E2329" }}
                tickLine={false}
              />
              <YAxis
                yAxisId="oi"
                domain={["dataMin - 0.5", "dataMax + 0.5"]}
                tick={{ fill: "#848E9C", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={60}
                tickFormatter={(v) => `${v.toFixed(2)}M`}
              />
              <YAxis
                yAxisId="vol"
                orientation="right"
                tick={{ fill: "#848E9C", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={50}
                tickFormatter={(v) => `${v.toFixed(2)}M`}
              />
              <Tooltip
                contentStyle={{
                  background: "#181A20",
                  border: "1px solid #2B3139",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                labelStyle={{ color: "#848E9C" }}
              />
              <Bar
                yAxisId="vol"
                dataKey="volume"
                fill="#474D57"
                barSize={6}
                radius={[1, 1, 0, 0]}
              />
              <Line
                yAxisId="oi"
                type="monotone"
                dataKey="oi"
                stroke="#F0B90B"
                strokeWidth={1.5}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>

          <Legend
            items={[
              { color: "#F0B90B", label: "Сумма открытых позиций (MON)" },
              { color: "#474D57", label: "Торговый объём (MON)", isBar: true },
            ]}
          />
        </div>

        {/* ---------------- Funding Rate ---------------- */}
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 600, margin: "0 0 12px" }}>
            Ставка финансирования
          </h3>

          <ResponsiveContainer width="100%" height={260} style={{ marginTop: 40 }}>
            <LineChart data={fundingData} margin={{ left: 0, right: 8, top: 40 }}>
              <CartesianGrid
                stroke="#1E2329"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="date"
                tick={{ fill: "#848E9C", fontSize: 11 }}
                axisLine={{ stroke: "#1E2329" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#848E9C", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={65}
                tickFormatter={(v) => `${v.toFixed(4)}%`}
              />
              <Tooltip
                contentStyle={{
                  background: "#181A20",
                  border: "1px solid #2B3139",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                labelStyle={{ color: "#848E9C" }}
                formatter={(v) => [`${v}%`, "Ставка"]}
              />
              <Line
                type="monotone"
                dataKey="rate"
                stroke="#F6465D"
                strokeWidth={1.5}
                dot={false}
                // сегменты выше нуля красим зелёным через segment-функцию recharts не поддерживает
                // нативно, поэтому на практике здесь строится две линии (см. пояснение ниже)
              />
            </LineChart>
          </ResponsiveContainer>

          <Legend
            items={[
              { color: "#0ECB81", label: "Позитивная" },
              { color: "#F6465D", label: "Негативная" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function Legend({ items }) {
  return (
    <div style={{ display: "flex", gap: 16, marginTop: 10 }}>
      {items.map((it) => (
        <div
          key={it.label}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
            color: "#848E9C",
          }}
        >
          <span
            style={{
              width: it.isBar ? 8 : 12,
              height: it.isBar ? 8 : 2,
              background: it.color,
              borderRadius: it.isBar ? 2 : 1,
              display: "inline-block",
            }}
          />
          {it.label}
        </div>
      ))}
    </div>
  );
}
