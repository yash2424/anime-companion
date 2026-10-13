// Loaded into pi when the brain preset uses provider "pi" (your subscription login through pi).
// Pi makes the model call; this extension hands it the companion's system prompt for each reply and a
// look_at_screen tool. Both come from the companion server, guarded by a per-run token.
const BASE = process.env.COMPANION_URL ?? "http://127.0.0.1:8765";
const headers = { "X-Companion-Token": process.env.COMPANION_PI_TOKEN ?? "" };

async function bridge(path: string): Promise<any> {
	const response = await fetch(BASE + path, { headers });
	if (!response.ok) throw new Error(`companion server returned ${response.status}`);
	return response.json();
}

export default function companionBridge(pi: any) {
	pi.on("before_agent_start", async () => {
		const { system } = await bridge("/api/pi/system");
		return system ? { systemPrompt: system } : undefined;
	});

	pi.registerTool({
		name: "look_at_screen",
		label: "Look at screen",
		description:
			"Take a screenshot of the window the user currently has open on their PC (never the companion itself). " +
			"Call this whenever the user refers to what they are doing, watching, reading, playing or working on, " +
			"asks for help with something on screen, or says things like 'look', 'see this', 'what do you think of this'.",
		parameters: { type: "object", properties: {}, additionalProperties: false },
		async execute() {
			const shot = await bridge("/api/pi/look");
			const content: any[] = [{ type: "text", text: shot.text }];
			if (shot.image) content.push({ type: "image", data: shot.image, mimeType: "image/jpeg" });
			return { content, details: {} };
		},
	});
}
