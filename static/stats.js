// SF6 Match Statistics JavaScript

let charts = {};

document.addEventListener('DOMContentLoaded', async () => {
    await loadStatistics();
    await loadMRHistory();

    // 30초마다 자동 갱신
    setInterval(async () => {
        await loadStatistics();
        await loadMRHistory();
    }, 30000); // 30000ms = 30초
});

async function loadStatistics() {
    try {
        // Get limit from localStorage, default to 100
        const limit = localStorage.getItem('mrChartLimit') || 100;
        const res = await fetch(`/api/stats/summary?limit=${limit}`);
        if (!res.ok) return;

        const data = await res.json();

        // 최근 N개 제목 업데이트
        document.getElementById('recent100Title').textContent = `RECENT ${limit}`;

        // 1. Total Win Rate
        updateStatCard('total', data.total.wins, data.total.losses);

        // 2. Recent 100
        updateStatCard('recent100', data.recent_100.wins, data.recent_100.losses);

        // 3. VS Character
        if (data.last_opponent_char) {
            document.getElementById('lastOpponentTitle').textContent = `vs ${data.last_opponent_char.character}`;
            updateStatCard('lastOpponent', data.last_opponent_char.wins, data.last_opponent_char.losses);
        } else {
            document.getElementById('lastOpponentTitle').textContent = `vs Char`;
            resetStatCard('lastOpponent');
        }

        // 4. VS Player
        if (data.last_opponent_name) {
            document.getElementById('selectedOpponentTitle').textContent = `vs ${data.last_opponent_name.name}`;
            updateStatCard('selectedOpponent', data.last_opponent_name.wins, data.last_opponent_name.losses);
        } else {
            document.getElementById('selectedOpponentTitle').textContent = `vs Player`;
            resetStatCard('selectedOpponent');
        }

    } catch (e) {
        console.error('Failed to load statistics:', e);
    }
}

function updateStatCard(prefix, wins, losses) {
    const total = wins + losses;
    const winRate = total > 0 ? ((wins / total) * 100).toFixed(1) : 0;

    // Update Text
    document.getElementById(`${prefix}WinRate`).textContent = `${winRate}%`;
    document.getElementById(`${prefix}Record`).textContent = `${wins}W ${losses}L`;

    // Update Progress Bar
    const progressBar = document.getElementById(`${prefix}ProgressBar`);
    if (progressBar) {
        // 0%일 때도 최소한의 바는 안보이게, 승률만큼 너비 조정
        progressBar.style.width = `${winRate}%`;
    }
}

function resetStatCard(prefix) {
    document.getElementById(`${prefix}WinRate`).textContent = '-';
    document.getElementById(`${prefix}Record`).textContent = '-';
    const progressBar = document.getElementById(`${prefix}ProgressBar`);
    if (progressBar) progressBar.style.width = '0%';
}

async function loadMRHistory() {
    try {
        const limit = localStorage.getItem('mrChartLimit') || 100;
        const res = await fetch(`/api/stats/mr_history?limit=${limit}`);
        if (!res.ok) return;

        const history = await res.json();
        if (history.length === 0) return;

        const ctx = document.getElementById('mrHistoryChart').getContext('2d');

        // 데이터 준비
        const labels = history.map((h, i) => i + 1);
        const mrValues = history.map(h => h.mr);

        // 그라데이션 생성 (More visible)
        const gradient = ctx.createLinearGradient(0, 0, 0, 180); // Adjusted height
        gradient.addColorStop(0, 'rgba(0, 255, 255, 0.6)'); // Bright Cyan, higher opacity
        gradient.addColorStop(1, 'rgba(0, 255, 255, 0.0)');

        // 기존 차트 제거
        if (charts.mrHistory) {
            charts.mrHistory.destroy();
        }

        charts.mrHistory = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'MR',
                    data: mrValues,
                    borderColor: '#00ffff', // Pure Cyan
                    backgroundColor: gradient,
                    borderWidth: 4, // Thicker line
                    pointBackgroundColor: '#ffffff',
                    pointBorderColor: '#00ffff',
                    pointBorderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 6,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(0,0,0,0.8)',
                        titleColor: '#a0a0a0',
                        bodyFont: { size: 14, weight: 'bold' },
                        callbacks: {
                            label: function (context) {
                                return `MR: ${context.parsed.y}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        display: false // X축 숨김 (깔끔하게)
                    },
                    y: {
                        display: true,
                        position: 'right',
                        grid: {
                            color: 'rgba(255, 255, 255, 0.1)', // More visible grid
                            drawBorder: false
                        },
                        ticks: {
                            color: '#ffffff',
                            font: { size: 16, weight: 'bold', family: 'Inter' }, // Larger, specific font
                            maxTicksLimit: 3,
                            textStrokeColor: '#000000', // Pure black shadow
                            textStrokeWidth: 4, // Stronger outline
                            z: 10 // Ensure on top
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    } catch (e) {
        console.error('Failed to load MR history:', e);
    }
}
