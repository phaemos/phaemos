// I make this a Server Component so the device data can be fetched on the
// server and the page is SEO-friendly - search crawlers will see the full
// device name in the heading rather than a client-side loading state.

// TODO: fetch device by ID and render SensorGrid with latest telemetry

// I use Promise<{ id: string }> here because Next.js 15 changed params to be
// async - the dynamic segment is now a Promise that must be awaited before
// reading the id value. Using the old synchronous type causes a build error.
interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function DeviceDetailPage({ params }: PageProps) {
  const { id } = await params;

  return (
    <main className="p-6 max-w-7xl mx-auto">
      <h1 className="text-xl font-semibold text-gray-100 mb-6">
        Device:{' '}
        <span className="font-mono text-blue-400">{id}</span>
      </h1>

      {/* TODO: replace with real device fetch + SensorGrid once the data
          layer is wired up. Something like:
          const device = await fetchDeviceById(id);
          const latest = await fetchLatestTelemetry(id);
          return <SensorGrid reading={latest} />
      */}
      <p className="text-gray-500 text-sm">
        Device detail view - implementation pending.
      </p>
    </main>
  );
}
