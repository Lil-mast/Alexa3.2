import type { CSSProperties } from "react";

import type { HouseClimate, HouseLight } from "../../api/types";

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Room extends Box {
  id: string;
}

// The four rooms the server controls. Their ids are the wire values, so the
// names and levels come from the server and this file only decides the layout.
const ROOMS: Room[] = [
  { id: "living_room", x: 30, y: 30, w: 290, h: 220 },
  { id: "kitchen", x: 320, y: 30, w: 270, h: 140 },
  { id: "office", x: 320, y: 170, w: 130, h: 110 },
  { id: "bedroom", x: 30, y: 250, w: 290, h: 180 },
];

// Rooms the house has but the assistant does not control. They frame the plan.
const DECOR_ROOMS: Array<Box & { label: string }> = [
  { label: "Bath", x: 450, y: 170, w: 140, h: 110 },
  { label: "Hall", x: 320, y: 280, w: 270, h: 150 },
];

const FURNITURE: Array<Box & { rx: number }> = [
  { x: 56, y: 196, w: 132, h: 28, rx: 8 },
  { x: 110, y: 150, w: 52, h: 30, rx: 4 },
  { x: 270, y: 70, w: 36, h: 10, rx: 2 },
  { x: 336, y: 132, w: 244, h: 18, rx: 0 },
  { x: 430, y: 96, w: 112, h: 32, rx: 6 },
  { x: 338, y: 250, w: 96, h: 20, rx: 3 },
  { x: 466, y: 236, w: 108, h: 30, rx: 15 },
  { x: 54, y: 340, w: 124, h: 76, rx: 6 },
  { x: 58, y: 344, w: 52, h: 18, rx: 6 },
  { x: 120, y: 344, w: 52, h: 18, rx: 6 },
  { x: 196, y: 330, w: 26, h: 26, rx: 4 },
  { x: 236, y: 300, w: 72, h: 18, rx: 3 },
  { x: 352, y: 330, w: 40, h: 20, rx: 4 },
  { x: 552, y: 392, w: 14, h: 14, rx: 7 },
];

interface Props {
  lights: HouseLight[];
  climate: HouseClimate[];
  /** Per-room counters. A new value restarts that room's highlight animation. */
  flashes: Record<string, number>;
}

function glowStyle(on: boolean, brightness: number): CSSProperties {
  return { opacity: on ? 0.25 + (brightness / 100) * 0.75 : 0 };
}

export default function HouseFloorPlan({ lights, climate, flashes }: Props) {
  const lightOf = (id: string) => lights.find((light) => light.room === id);
  const climateOf = (id: string) => climate.find((zone) => zone.zone === id);

  const summary = ROOMS.map((room) => {
    const light = lightOf(room.id);
    const zone = climateOf(room.id);
    const name = light?.room_name ?? zone?.zone_name ?? room.id;
    const lightText = light?.on ? `lights at ${light.brightness} percent` : "lights off";
    const temperature = zone ? `, set to ${zone.target_c} degrees` : "";
    return `${name}: ${lightText}${temperature}`;
  }).join(". ");

  return (
    <svg className="hs-plan" viewBox="0 0 620 460" role="img" aria-labelledby="hs-plan-title">
      <title id="hs-plan-title">{summary}</title>
      <defs>
        <radialGradient id="hs-glow">
          <stop className="hs-glow-core" offset="0%" />
          <stop className="hs-glow-edge" offset="100%" />
        </radialGradient>
      </defs>

      <rect className="hs-floor" x="0" y="0" width="620" height="460" />

      {ROOMS.map((room) => (
        <rect key={room.id} className="hs-room-bg" x={room.x} y={room.y} width={room.w} height={room.h} />
      ))}
      {DECOR_ROOMS.map((room) => (
        <rect
          key={room.label}
          className="hs-room-bg hs-room-decor"
          x={room.x}
          y={room.y}
          width={room.w}
          height={room.h}
        />
      ))}

      {ROOMS.map((room) => {
        const light = lightOf(room.id);
        return (
          <ellipse
            key={room.id}
            className="hs-glow"
            cx={room.x + room.w / 2}
            cy={room.y + room.h / 2 + 8}
            rx={Math.min(room.w, room.h) * 0.42}
            ry={Math.min(room.w, room.h) * 0.36}
            style={glowStyle(light?.on ?? false, light?.brightness ?? 0)}
          />
        );
      })}

      {ROOMS.map((room) =>
        flashes[room.id] ? (
          <rect
            key={`${room.id}-${flashes[room.id]}`}
            className="hs-flash"
            x={room.x}
            y={room.y}
            width={room.w}
            height={room.h}
          />
        ) : null,
      )}

      {FURNITURE.map((piece, index) => (
        <rect
          key={index}
          className="hs-furn"
          x={piece.x}
          y={piece.y}
          width={piece.w}
          height={piece.h}
          rx={piece.rx}
        />
      ))}

      {ROOMS.map((room) => {
        const light = lightOf(room.id);
        const zone = climateOf(room.id);
        const name = (light?.room_name ?? zone?.zone_name ?? room.id).toUpperCase();
        const lightText = light?.on ? `Lights ${light.brightness}%` : "Lights off";
        const temperature = zone ? `${zone.target_c}°C` : "";
        return (
          <g key={room.id} aria-hidden="true">
            <text className="hs-room-name" x={room.x + 14} y={room.y + 26}>
              {name}
            </text>
            <text className="hs-room-meta" x={room.x + 14} y={room.y + 46}>
              {temperature}
            </text>
            <text className="hs-room-meta" x={room.x + 14} y={room.y + 64}>
              {lightText}
            </text>
          </g>
        );
      })}

      {DECOR_ROOMS.map((room) => (
        <text key={room.label} className="hs-room-name hs-room-name-muted" x={room.x + 14} y={room.y + 26}>
          {room.label.toUpperCase()}
        </text>
      ))}

      {[...ROOMS, ...DECOR_ROOMS].map((room) => (
        <rect
          key={`wall-${room.x}-${room.y}`}
          className="hs-wall"
          x={room.x}
          y={room.y}
          width={room.w}
          height={room.h}
        />
      ))}
    </svg>
  );
}
