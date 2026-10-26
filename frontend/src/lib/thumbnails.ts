// Renders one small picture per feature step: the part right after that feature,
// with the faces the feature created in the accent colour. One shared offscreen
// renderer keeps the number of WebGL contexts down.
import * as THREE from "three";
import type { MeshPayload } from "../api";
import { decodeMesh } from "./mesh";

let renderer: THREE.WebGLRenderer | null = null;

function cssColor(name: string): THREE.Color {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(value || "#888888");
}

function geometryFor(mesh: MeshPayload, feature: string, base: THREE.Color, fresh: THREE.Color) {
  const decoded = decodeMesh(mesh);
  const colors = new Float32Array(decoded.positions.length);
  decoded.faces.forEach((face, i) => {
    const c = face.feature === feature ? fresh : base;
    const [lo, hi] = decoded.faceVertices[i];
    for (let v = lo; v <= hi; v++) colors.set([c.r, c.g, c.b], v * 3);
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(decoded.positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.setIndex(new THREE.BufferAttribute(decoded.indices, 1));
  geometry.computeVertexNormals();
  return geometry;
}

export function renderStepThumbnails(
  steps: { id: string; mesh: MeshPayload | null }[],
  width = 168,
  height = 126,
): Map<string, string> {
  const out = new Map<string, string>();
  const usable = steps.filter((s) => s.mesh);
  if (usable.length === 0) return out;
  try {
    renderer ??= new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  } catch {
    return out; // no WebGL: the blocks still work, just without pictures
  }
  renderer.setPixelRatio(2);
  renderer.setSize(width, height, false);

  const base = cssColor("--vp-part");
  const fresh = cssColor("--vp-select");
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7a8c, 1.6));
  const camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 10000);
  camera.up.set(0, 0, 1);
  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(1, 1.5, 2);
  camera.add(key);
  scene.add(camera);

  // Frame every step on the finished part so the pictures read as a sequence.
  const last = geometryFor(usable[usable.length - 1].mesh!, "", base, fresh);
  last.computeBoundingSphere();
  const sphere = last.boundingSphere!;
  last.dispose();
  const distance = (sphere.radius / Math.sin(THREE.MathUtils.degToRad(15))) * 1.05;
  camera.position.copy(sphere.center).addScaledVector(new THREE.Vector3(1, -1.25, 0.95).normalize(), distance);
  camera.lookAt(sphere.center);

  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.05, side: THREE.DoubleSide });
  for (const step of usable) {
    const geometry = geometryFor(step.mesh!, step.id, base, fresh);
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    renderer.render(scene, camera);
    out.set(step.id, renderer.domElement.toDataURL("image/png"));
    scene.remove(mesh);
    geometry.dispose();
  }
  material.dispose();
  return out;
}
