import React, { useState, useCallback } from 'react';
import { View, StyleSheet, TouchableOpacity, Text } from 'react-native';
import { Canvas, RoundedRect, Text as SkiaText, useFont, Circle } from '@shopify/react-native-skia';
import { useTheme } from '../theme/ThemeProvider';
import { useGameStore } from '../store/useGameStore';
import { UpgradeBuildingModal } from './UpgradeBuildingModal';
import type { Building } from '../types';

// ─── Sanctuary Canvas ─────────────────────────────────────────────────────────
// Renders the town-builder game view using React Native Skia.
// All game graphics live inside a single <Canvas> element at the bottom of the
// z-index. The <UpgradeBuildingModal> is a standard RN overlay on top.
//
// Building layout: a 2×2 grid of 120×100 px tiles. Each tile is drawn with
// Skia primitives. Tapping a building opens the upgrade modal.

const CANVAS_HEIGHT = 320;
const TILE_W = 120;
const TILE_H = 100;
const TILE_GAP = 12;

// Fixed layout positions for up to 4 buildings
const POSITIONS = [
  { x: 20, y: 20 },
  { x: 164, y: 20 },
  { x: 20, y: 144 },
  { x: 164, y: 144 },
];

// Building colour by type
const BUILDING_COLORS: Record<string, string> = {
  APOTHECARY: '#10b981',
  TOWER: '#6366f1',
  GARDEN: '#f59e0b',
  FORGE: '#ef4444',
};

const BUILDING_ICON: Record<string, string> = {
  APOTHECARY: '⚗',
  TOWER: '🗼',
  GARDEN: '🌿',
  FORGE: '⚒',
};

interface BuildingTileProps {
  building: Building;
  x: number;
  y: number;
  onTap: (building: Building) => void;
}

function BuildingTile({ building, x, y, onTap }: BuildingTileProps) {
  const color = BUILDING_COLORS[building.type] ?? '#888';
  const alpha = building.isUpgrading ? 0.6 : 1;

  return (
    <>
      {/* Background card */}
      <RoundedRect
        x={x}
        y={y}
        width={TILE_W}
        height={TILE_H}
        r={12}
        color={color + '33'}
      />
      {/* Border */}
      <RoundedRect
        x={x}
        y={y}
        width={TILE_W}
        height={TILE_H}
        r={12}
        color={color + '99'}
        style="stroke"
        strokeWidth={1.5}
      />
      {/* Tier indicator dots */}
      {Array.from({ length: building.tier }).map((_, i) => (
        <Circle
          key={i}
          cx={x + 10 + i * 12}
          cy={y + TILE_H - 10}
          r={4}
          color={color}
        />
      ))}
      {/* Upgrading overlay */}
      {building.isUpgrading && (
        <RoundedRect
          x={x}
          y={y}
          width={TILE_W}
          height={TILE_H}
          r={12}
          color="#000000aa"
        />
      )}
    </>
  );
}

export function SanctuaryCanvas() {
  const { theme } = useTheme();
  const buildings = useGameStore((s) => s.sanctuary.buildings);
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);

  // Determine which building was tapped based on touch coordinates
  const handleCanvasTap = useCallback(
    (event: { nativeEvent: { locationX: number; locationY: number } }) => {
      const { locationX, locationY } = event.nativeEvent;
      for (let i = 0; i < POSITIONS.length; i++) {
        const pos = POSITIONS[i];
        const building = buildings[i];
        if (!building) continue;
        if (
          locationX >= pos.x &&
          locationX <= pos.x + TILE_W &&
          locationY >= pos.y &&
          locationY <= pos.y + TILE_H
        ) {
          setSelectedBuilding(building);
          return;
        }
      }
    },
    [buildings],
  );

  return (
    <View style={styles.wrapper}>
      {/* Skia Canvas — game graphics layer */}
      <TouchableOpacity
        onPress={handleCanvasTap}
        activeOpacity={1}
        style={styles.canvasContainer}
      >
        <Canvas style={[styles.canvas, { height: CANVAS_HEIGHT }]}>
          {buildings.slice(0, 4).map((building, i) => {
            const pos = POSITIONS[i];
            return (
              <BuildingTile
                key={building.id}
                building={building}
                x={pos.x}
                y={pos.y}
                onTap={setSelectedBuilding}
              />
            );
          })}
        </Canvas>
      </TouchableOpacity>

      {/* Emoji labels — rendered as RN View overlay for simplicity */}
      {buildings.slice(0, 4).map((building, i) => {
        const pos = POSITIONS[i];
        return (
          <TouchableOpacity
            key={building.id}
            onPress={() => setSelectedBuilding(building)}
            style={[
              styles.buildingLabel,
              {
                left: pos.x + TILE_W / 2 - 30,
                top: pos.y + TILE_H / 2 - 22,
              },
            ]}
          >
            <Text style={styles.buildingIcon}>
              {BUILDING_ICON[building.type] ?? '🏛'}
            </Text>
            <Text
              style={[
                styles.buildingName,
                { color: BUILDING_COLORS[building.type] ?? '#fff' },
              ]}
            >
              {building.isUpgrading ? '⏳' : `T${building.tier}`}
            </Text>
          </TouchableOpacity>
        );
      })}

      {/* Upgrade modal — standard RN overlay above canvas */}
      <UpgradeBuildingModal
        building={selectedBuilding}
        onClose={() => setSelectedBuilding(null)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    height: CANVAS_HEIGHT,
    position: 'relative',
  },
  canvasContainer: {
    ...StyleSheet.absoluteFillObject,
  },
  canvas: {
    flex: 1,
  },
  buildingLabel: {
    position: 'absolute',
    width: 60,
    alignItems: 'center',
    pointerEvents: 'none',
  },
  buildingIcon: {
    fontSize: 28,
  },
  buildingName: {
    fontSize: 11,
    fontWeight: '700',
  },
});
